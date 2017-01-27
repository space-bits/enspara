import os
import shutil
import tempfile
import pickle
import json

import numpy as np
from scipy import sparse
from scipy.io import mmwrite, mmread

from . import builders
from .transition_matrices import assigns_to_counts, TrimMapping, \
    eq_probs, trim_disconnected


class MSM:

    __slots__ = ['lag_time', 'sliding_window', 'trim', 'method',
                 'tcounts_', 'tprobs_', 'eq_probs_', 'mapping_']

    def __init__(self, lag_time, method, trim=False, sliding_window=True):

        self.lag_time = lag_time
        self.trim = trim

        if callable(method):
            self.method = method
        else:
            self.method = getattr(builders, method)
        self.sliding_window = True

    def fit(self, assigns):

        tcounts = assigns_to_counts(
            assigns,
            lag_time=self.lag_time,
            sliding_window=self.sliding_window)
        self.tcounts_ = tcounts

        if self.trim:
            self.mapping_, tcounts = trim_disconnected(tcounts)
        else:
            self.mapping_ = TrimMapping(zip(range(self.n_states),
                                            range(self.n_states)))

        self.tprobs_ = self.method(tcounts)
        self.eq_probs_ = eq_probs(self.tprobs_)

    @property
    def n_states(self):
        if hasattr(self, 'tcounts_'):
            return self.tcounts_.shape[0]
        else:
            return None

    @property
    def config(self):
        return {
            'lag_time': self.lag_time,
            'sliding_window': self.sliding_window,
            'trim': self.trim,
            'method': self.method,
        }

    @property
    def fit_result_(self):
        if self.tcounts_ is not None:
            assert self.tprobs_ is not None
            assert self.mapping_ is not None
            assert self.eq_probs_ is not None

            return {
                'tcounts_': self.tcounts_,
                'tprobs_': self.tprobs_,
                'eq_probs_': self.eq_probs_,
                'mapping_': self.mapping_
            }
        else:
            assert self.tprobs_ is None
            assert self.mapping_ is None
            assert self.eq_probs_ is None
            return None

    def __eq__(self, other):
        if self is other:
            return True
        else:
            if self.config != other.config:
                return False

            if self.fit_result_ is None:
                # one is not fit, equality if neither is
                return other.fit_result_ is None
            else:
                # eq probs can do numpy comparison (dense)
                if not np.allclose(self.eq_probs_, other.eq_probs_):
                    return False

                if self.mapping_ != other.mapping_:
                    return False

                # compare tcounts, tprobs shapes.
                if self.tcounts_.shape != other.tcounts_.shape or \
                   self.tprobs_.shape != other.tprobs_.shape:
                    return False

                # identical shapes => use nnz for element-wise equality
                if (self.tcounts_ != other.tcounts_).nnz != 0:
                    return False

                # imperfect serialization leads to diff in tprobs, use
                # allclose instead of all
                f_self = sparse.find(self.tprobs_)
                f_other = sparse.find(other.tprobs_)

                if not np.all(f_self[0] == f_other[0]) or \
                   not np.all(f_self[1] == f_other[1]):
                    return False

                if not np.allclose(f_self[2], f_other[2]):
                    return False

                return True

    def __repr__(self):
        return str(self)

    def __str__(self):
        s = "MSM:"+str({
                'config': self.config,
                'fit': self.fit_result_
            })

        return s

    @classmethod
    def load(cls, path, manifest='manifest.json'):
        if not os.path.isdir(path):
            raise NotImplementedError("MSMs don't handle zip archives yet.")

        with open(os.path.join(path, manifest)) as f:
            fname_dict = json.load(f)

        # decorate fname_dict values with path
        fname_dict = {k: os.path.join(path, v) for k, v in fname_dict.items()}

        with open(fname_dict['config'], 'rb') as f:
            config = pickle.load(f)

        msm = MSM(**config)

        msm.tcounts_ = mmread(fname_dict['tcounts_'])
        msm.tprobs_ = mmread(fname_dict['tprobs_'])
        msm.mapping_ = TrimMapping.load(fname_dict['mapping_'])
        with open(fname_dict['eq_probs_'], 'r') as f:
            msm.eq_probs_ = np.array(list(map(float, f.readlines())))

        return msm

    def save(self, path, force=False, zipfile=False, **filenames):

        fname_dict = {
            'mapping_': 'mapping.csv',
            'tcounts_': 'tcounts.mtx',
            'tprobs_': 'tprobs.mtx',
            'eq_probs_': 'eq-probs.dat',
            'config': 'config.pkl',
        }

        fname_dict.update(filenames)

        with tempfile.TemporaryDirectory(prefix=os.path.basename(path)) as \
                tempdir:

            def tmp_fname(prop):
                return os.path.join(tempdir, fname_dict[prop])

            with open(os.path.join(tempdir, 'manifest.json'), 'w') as f:
                json.dump(fname_dict, f, sort_keys=True, indent=4,
                          separators=(',', ': '))

            with open(tmp_fname('mapping_'), 'w') as f:
                self.mapping_.write(f)
            with open(tmp_fname('tcounts_'), 'wb') as f:
                mmwrite(f, self.tcounts_)
            with open(tmp_fname('tprobs_'), 'wb') as f:
                mmwrite(f, self.tprobs_)
            with open(tmp_fname('eq_probs_'), 'w') as f:
                f.write("\n".join(map(str, [p for p in self.eq_probs_])))
            with open(tmp_fname('config'), 'wb') as f:
                pickle.dump(self.config, f)

            if force and os.path.isdir(path):
                os.remove(path)

            if zipfile:
                raise NotImplementedError("MSMs don't do zip archives yet.")
            else:
                shutil.copytree(tempdir, path)

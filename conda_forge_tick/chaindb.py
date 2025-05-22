"""
The code in this module is from xonsh (https://github.com/xonsh/xonsh/blob/main/xonsh/lib/collections.py).

License:

Copyright 2015-2016, the xonsh developers. All rights reserved.

Redistribution and use in source and binary forms, with or without modification, are
permitted provided that the following conditions are met:

   1. Redistributions of source code must retain the above copyright notice, this list of
      conditions and the following disclaimer.

   2. Redistributions in binary form must reproduce the above copyright notice, this list
      of conditions and the following disclaimer in the documentation and/or other materials
      provided with the distribution.

THIS SOFTWARE IS PROVIDED BY THE XONSH DEVELOPERS ``AS IS'' AND ANY EXPRESS OR IMPLIED
WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND
FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE XONSH DEVELOPERS OR
CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON
ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF
ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

The views and conclusions contained in the software and documentation are those of the
authors and should not be interpreted as representing official policies, either expressed
or implied, of the stakeholders of the xonsh project or the employers of xonsh developers.
"""

import itertools
import typing as tp
from collections import ChainMap
from collections.abc import MutableMapping, MutableSequence, MutableSet


class ChainDBDefaultType:
    """Singleton for representing when no default value is given."""

    __inst: tp.Optional["ChainDBDefaultType"] = None

    def __new__(cls):
        if ChainDBDefaultType.__inst is None:
            ChainDBDefaultType.__inst = object.__new__(cls)
        return ChainDBDefaultType.__inst


ChainDBDefault = ChainDBDefaultType()


class ChainDB(ChainMap):
    """A ChainMap who's ``_getitem__`` returns either a ChainDB or
    the result. The results resolve to the outermost mapping.
    """

    def __getitem__(self, key):
        res = None
        results = []
        # Try to get all the data from all the mappings
        for mapping in self.maps:
            results.append(mapping.get(key, ChainDBDefault))
        # if all the results are mapping create a ChainDB
        if all([isinstance(result, MutableMapping) for result in results]):
            for result in results:
                if res is None:
                    res = ChainDB(result)
                else:
                    res.maps.append(result)
        elif all(
            [isinstance(result, (MutableSequence, MutableSet)) for result in results]
        ):
            results_chain = itertools.chain(*results)
            # if all results have the same type, cast into that type
            if all([isinstance(result, type(results[0])) for result in results]):
                return type(results[0])(results_chain)
            else:
                return list(results_chain)
        else:
            for result in reversed(results):
                if result is not ChainDBDefault:
                    return result
            raise KeyError(f"{key} is none of the current mappings")
        return res

    def __setitem__(self, key, value):
        if key not in self:
            super().__setitem__(key, value)
        else:
            # Try to get all the data from all the mappings
            for mapping in reversed(self.maps):
                if key in mapping:
                    mapping[key] = value


def _convert_to_dict(cm):
    if isinstance(cm, (ChainMap, ChainDB)):
        r = {}
        for k, v in cm.items():
            r[k] = _convert_to_dict(v)
        return r
    else:
        return cm

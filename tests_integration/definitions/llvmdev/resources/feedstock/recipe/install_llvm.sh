#!/bin/bash
set -ex

IFS='.' read -ra VER_ARR <<< "$PKG_VERSION"

# temporary prefix to be able to install files more granularly
mkdir temp_prefix

MAJOR_VER="${VER_ARR[0]}"
MAJOR_EXT="${MAJOR_VER}"
# default SOLVER for tagged releases is major.minor version
SOLVER_EXT="${VER_ARR[0]}.${VER_ARR[1]}"
# for rc's, both MAJOR_EXT & SOLVER_EXT get suffixes
if [[ "${PKG_VERSION}" == *rc* ]]; then
    # rc's get "-rcX" suffix; in this case, PKG_VERSION has 4 parts,
    # (e.g. 19.1.0.rc1), so take the last part after splitting on "."
    MAJOR_EXT="${MAJOR_EXT}-${VER_ARR[3]}"
    SOLVER_EXT="${SOLVER_EXT}-${VER_ARR[3]}"
elif [[ "${PKG_VERSION}" == *dev* ]]; then
    # otherwise with git suffix
    MAJOR_EXT="${MAJOR_EXT}git"
    SOLVER_EXT="${SOLVER_EXT}git"
fi

if [[ "${PKG_NAME}" == libllvm-c* ]]; then
    cmake --install ./build --prefix=./temp_prefix
    # only libLLVM-C
    mv ./temp_prefix/lib/libLLVM-C${SOLVER_EXT}${SHLIB_EXT} $PREFIX/lib
elif [[ "${PKG_NAME}" == libllvm* ]]; then
    cmake --install ./build --prefix=./temp_prefix
    # all other libraries
    mv ./temp_prefix/lib/libLLVM-${MAJOR_EXT}${SHLIB_EXT} $PREFIX/lib
    mv ./temp_prefix/lib/lib*.so.${SOLVER_EXT} $PREFIX/lib || true
    mv ./temp_prefix/lib/lib*.${SOLVER_EXT}.dylib $PREFIX/lib || true
elif [[ "${PKG_NAME}" == "llvm-tools-${MAJOR_VER}" ]]; then
    cmake --install ./build --prefix=./temp_prefix
    # install all binaries with a -${MAJOR_VER}
    pushd ./temp_prefix
      for f in bin/*; do
        cp $f $PREFIX/bin/$(basename $f)-${MAJOR_VER}
      done
    popd
    # except one binary that belongs to llvmdev
    rm $PREFIX/bin/llvm-config-${MAJOR_VER}
elif [[ "${PKG_NAME}" == "llvm-tools" ]]; then
    cmake --install ./build --prefix=./temp_prefix
    # Install a symlink without the major version
    pushd ./temp_prefix
      for f in bin/*; do
        ln -sf $PREFIX/bin/$(basename $f)-${MAJOR_VER} $PREFIX/bin/$(basename $f)
      done
    popd
    # opt-viewer tool
    mv ./temp_prefix/share/* $PREFIX/share
    rm $PREFIX/bin/llvm-config
else
    # llvmdev: install everything else
    cmake --install ./build --prefix=$PREFIX
fi

rm -rf temp_prefix

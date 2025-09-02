import os
import secrets

import networkx as nx

from conda_forge_tick.contexts import ClonedFeedstockContext
from conda_forge_tick.migrators.core import Migrator, get_outputs_lut

RNG = secrets.SystemRandom()

BROKEN_PACKAGES = """\
linux-ppc64le/adios2-2.7.1-mpi_mpich_py36ha1d8cba_0.tar.bz2
linux-ppc64le/adios2-2.7.1-mpi_mpich_py36hbc05bcd_1.tar.bz2
linux-ppc64le/adios2-2.7.1-mpi_mpich_py37h4d01b4f_1.tar.bz2
linux-ppc64le/adios2-2.7.1-mpi_mpich_py37hac56ba2_0.tar.bz2
linux-ppc64le/adios2-2.7.1-mpi_mpich_py38h3c87899_0.tar.bz2
linux-ppc64le/adios2-2.7.1-mpi_mpich_py38h799e2cf_1.tar.bz2
linux-ppc64le/adios2-2.7.1-mpi_mpich_py39he9920ea_1.tar.bz2
linux-ppc64le/adios2-2.7.1-mpi_openmpi_py36h80d3435_0.tar.bz2
linux-ppc64le/adios2-2.7.1-mpi_openmpi_py36hc70a3cf_1.tar.bz2
linux-ppc64le/adios2-2.7.1-mpi_openmpi_py37h7dbbd9e_0.tar.bz2
linux-ppc64le/adios2-2.7.1-mpi_openmpi_py37hf0c940e_1.tar.bz2
linux-ppc64le/adios2-2.7.1-mpi_openmpi_py38h3360151_1.tar.bz2
linux-ppc64le/adios2-2.7.1-mpi_openmpi_py38hde5d84f_0.tar.bz2
linux-ppc64le/adios2-2.7.1-mpi_openmpi_py39hfd5a10e_1.tar.bz2
linux-ppc64le/adios2-2.7.1-nompi_py36ha06ad60_100.tar.bz2
linux-ppc64le/adios2-2.7.1-nompi_py36he81f073_101.tar.bz2
linux-ppc64le/adios2-2.7.1-nompi_py37h2c8cc97_101.tar.bz2
linux-ppc64le/adios2-2.7.1-nompi_py37hc8240a0_100.tar.bz2
linux-ppc64le/adios2-2.7.1-nompi_py38h1d39722_100.tar.bz2
linux-ppc64le/adios2-2.7.1-nompi_py38hebd67cc_101.tar.bz2
linux-ppc64le/adios2-2.7.1-nompi_py39he85a080_101.tar.bz2
linux-ppc64le/anyio-3.3.1-py36h270354c_0.tar.bz2
linux-ppc64le/anyio-3.3.1-py37h35e4cab_0.tar.bz2
linux-ppc64le/anyio-3.3.1-py38hf8b3453_0.tar.bz2
linux-ppc64le/aws-c-s3-0.1.23-h838eefd_2.tar.bz2
linux-ppc64le/awscli-1.20.36-py36h270354c_0.tar.bz2
linux-ppc64le/awscli-1.20.36-py37h35e4cab_0.tar.bz2
linux-ppc64le/awscli-1.20.36-py37hadc05a3_0.tar.bz2
linux-ppc64le/awscli-1.20.36-py38hf8b3453_0.tar.bz2
linux-ppc64le/awscli-1.20.36-py39hc1b9086_0.tar.bz2
linux-ppc64le/awscli-1.20.37-py36h270354c_0.tar.bz2
linux-ppc64le/awscli-1.20.37-py37h35e4cab_0.tar.bz2
linux-ppc64le/awscli-1.20.37-py37hadc05a3_0.tar.bz2
linux-ppc64le/awscli-1.20.37-py38hf8b3453_0.tar.bz2
linux-ppc64le/awscli-1.20.37-py39hc1b9086_0.tar.bz2
linux-ppc64le/awscli-1.20.38-py36h270354c_0.tar.bz2
linux-ppc64le/awscli-1.20.38-py37h35e4cab_0.tar.bz2
linux-ppc64le/awscli-1.20.38-py37hadc05a3_0.tar.bz2
linux-ppc64le/awscli-1.20.38-py38hf8b3453_0.tar.bz2
linux-ppc64le/awscli-1.20.38-py39hc1b9086_0.tar.bz2
linux-ppc64le/awscrt-0.12.1-py36h00ad570_1.tar.bz2
linux-ppc64le/awscrt-0.12.1-py37h4aa8152_1.tar.bz2
linux-ppc64le/awscrt-0.12.1-py37h88afbeb_1.tar.bz2
linux-ppc64le/awscrt-0.12.1-py38h912192e_1.tar.bz2
linux-ppc64le/awscrt-0.12.1-py39h18c439e_1.tar.bz2
linux-ppc64le/awscrt-0.12.2-py36h00ad570_0.tar.bz2
linux-ppc64le/awscrt-0.12.2-py36h62de085_2.tar.bz2
linux-ppc64le/awscrt-0.12.2-py36h6bcd0ee_1.tar.bz2
linux-ppc64le/awscrt-0.12.2-py36h97b1a3a_5.tar.bz2
linux-ppc64le/awscrt-0.12.2-py36hb2704bc_3.tar.bz2
linux-ppc64le/awscrt-0.12.2-py36hfd0e850_4.tar.bz2
linux-ppc64le/awscrt-0.12.2-py37h0e3a3e5_3.tar.bz2
linux-ppc64le/awscrt-0.12.2-py37h1529239_4.tar.bz2
linux-ppc64le/awscrt-0.12.2-py37h32e9d19_1.tar.bz2
linux-ppc64le/awscrt-0.12.2-py37h37d81fc_5.tar.bz2
linux-ppc64le/awscrt-0.12.2-py37h4aa8152_0.tar.bz2
linux-ppc64le/awscrt-0.12.2-py37h4c3c8a4_2.tar.bz2
linux-ppc64le/awscrt-0.12.2-py37h7d5ebc6_5.tar.bz2
linux-ppc64le/awscrt-0.12.2-py37h88afbeb_0.tar.bz2
linux-ppc64le/awscrt-0.12.2-py37h8d1dd6a_1.tar.bz2
linux-ppc64le/awscrt-0.12.2-py37hc689c71_2.tar.bz2
linux-ppc64le/awscrt-0.12.2-py37hf38e359_4.tar.bz2
linux-ppc64le/awscrt-0.12.2-py37hf98b87a_3.tar.bz2
linux-ppc64le/awscrt-0.12.2-py38h148e87a_4.tar.bz2
linux-ppc64le/awscrt-0.12.2-py38h62882cf_5.tar.bz2
linux-ppc64le/awscrt-0.12.2-py38h65f98c4_2.tar.bz2
linux-ppc64le/awscrt-0.12.2-py38h912192e_0.tar.bz2
linux-ppc64le/awscrt-0.12.2-py38hb881f1a_1.tar.bz2
linux-ppc64le/awscrt-0.12.2-py38hd298a99_3.tar.bz2
linux-ppc64le/awscrt-0.12.2-py39h03c2277_2.tar.bz2
linux-ppc64le/awscrt-0.12.2-py39h18c439e_0.tar.bz2
linux-ppc64le/awscrt-0.12.2-py39h210f7cb_1.tar.bz2
linux-ppc64le/awscrt-0.12.2-py39h9274f38_3.tar.bz2
linux-ppc64le/awscrt-0.12.2-py39h9e0ac5b_5.tar.bz2
linux-ppc64le/awscrt-0.12.2-py39hf904918_4.tar.bz2
linux-ppc64le/binutils_linux-ppc64le-2.36-he035471_1.tar.bz2
linux-ppc64le/bitarray-2.3.3-py36hc33305d_0.tar.bz2
linux-ppc64le/bitarray-2.3.3-py37h6642d69_0.tar.bz2
linux-ppc64le/bitarray-2.3.3-py38h98b8a6f_0.tar.bz2
linux-ppc64le/bitarray-2.3.3-py39ha810350_0.tar.bz2
linux-ppc64le/cherrypy-18.6.1-py36h270354c_0.tar.bz2
linux-ppc64le/cherrypy-18.6.1-py37h35e4cab_0.tar.bz2
linux-ppc64le/cherrypy-18.6.1-py37hadc05a3_0.tar.bz2
linux-ppc64le/cherrypy-18.6.1-py38hf8b3453_0.tar.bz2
linux-ppc64le/cherrypy-18.6.1-py39hc1b9086_0.tar.bz2
linux-ppc64le/cni-1.0.1-h79e4d75_0.tar.bz2
linux-ppc64le/conda-4.10.3-py36h270354c_1.tar.bz2
linux-ppc64le/conda-4.10.3-py37h35e4cab_1.tar.bz2
linux-ppc64le/conda-4.10.3-py37hadc05a3_1.tar.bz2
linux-ppc64le/conda-4.10.3-py38hf8b3453_1.tar.bz2
linux-ppc64le/conda-4.10.3-py39hc1b9086_1.tar.bz2
linux-ppc64le/cppzmq-4.8.0-h5c3ff33_0.tar.bz2
linux-ppc64le/flask-openid-1.3.0-py36h270354c_0.tar.bz2
linux-ppc64le/flask-openid-1.3.0-py37h35e4cab_0.tar.bz2
linux-ppc64le/flask-openid-1.3.0-py38hf8b3453_0.tar.bz2
linux-ppc64le/flask-openid-1.3.0-py39hc1b9086_0.tar.bz2
linux-ppc64le/gettext-0.19.8.1-h6603d1e_1006.tar.bz2
linux-ppc64le/gh-2.0.0-hdeebcfe_2.tar.bz2
linux-ppc64le/go-1.16.8-hb5868a7_0.tar.bz2
linux-ppc64le/go-1.16.8-hb986ca7_0.tar.bz2
linux-ppc64le/go-cgo-1.16.8-h1ef31ea_0.tar.bz2
linux-ppc64le/go-nocgo-1.16.8-h5b8e9f1_0.tar.bz2
linux-ppc64le/gst-libav-1.18.5-h00c311c_0.tar.bz2
linux-ppc64le/gst-plugins-bad-1.18.5-h819bb30_0.tar.bz2
linux-ppc64le/gst-plugins-ugly-1.18.5-h851bbad_0.tar.bz2
linux-ppc64le/imagecodecs-2021.7.30-py37h039678c_0.tar.bz2
linux-ppc64le/imagecodecs-2021.7.30-py37h8db4fa0_0.tar.bz2
linux-ppc64le/imagecodecs-2021.7.30-py38hc54d1fd_0.tar.bz2
linux-ppc64le/imagecodecs-2021.7.30-py39hb254224_0.tar.bz2
linux-ppc64le/iminuit-2.8.3-py36h08d3667_0.tar.bz2
linux-ppc64le/iminuit-2.8.3-py37hc9b93fd_0.tar.bz2
linux-ppc64le/iminuit-2.8.3-py37hfc837b7_0.tar.bz2
linux-ppc64le/iminuit-2.8.3-py38ha35a538_0.tar.bz2
linux-ppc64le/iminuit-2.8.3-py39had50986_0.tar.bz2
linux-ppc64le/jwt-cpp-0.5.2-h278a7c5_0.tar.bz2
linux-ppc64le/libffi-3.4.2-h3b9df90_1.tar.bz2
linux-ppc64le/libignition-utils1-1.1.0-h3b9df90_0.tar.bz2
linux-ppc64le/libm2k-0.5.0-py36h11d542b_0.tar.bz2
linux-ppc64le/libm2k-0.5.0-py37hc8d93d0_0.tar.bz2
linux-ppc64le/libm2k-0.5.0-py37hd738acd_0.tar.bz2
linux-ppc64le/libm2k-0.5.0-py38hebe9bed_0.tar.bz2
linux-ppc64le/libm2k-0.5.0-py39hdf75b26_0.tar.bz2
linux-ppc64le/libprotobuf-3.15.8-h690f14c_1.tar.bz2
linux-ppc64le/libprotobuf-static-3.15.8-ha3edaa6_1.tar.bz2
linux-ppc64le/libpython-static-3.9.6-h3b9df90_2_cpython.tar.bz2
linux-ppc64le/libxc-5.1.6-py36h6df7b01_0.tar.bz2
linux-ppc64le/libxc-5.1.6-py37h368636e_0.tar.bz2
linux-ppc64le/libxc-5.1.6-py37h4f88000_0.tar.bz2
linux-ppc64le/libxc-5.1.6-py38hc1f7224_0.tar.bz2
linux-ppc64le/libxc-5.1.6-py39hb2284b6_0.tar.bz2
linux-ppc64le/make_arq-0.1-py36h97d1520_2.tar.bz2
linux-ppc64le/make_arq-0.1-py37h56ea505_2.tar.bz2
linux-ppc64le/make_arq-0.1-py38h3ba5731_2.tar.bz2
linux-ppc64le/mlflow-1.20.2-py36ha29011c_0.tar.bz2
linux-ppc64le/mlflow-1.20.2-py37h1717c74_0.tar.bz2
linux-ppc64le/mlflow-1.20.2-py38hf366367_0.tar.bz2
linux-ppc64le/mlflow-1.20.2-py39ha92320b_0.tar.bz2
linux-ppc64le/mlflow-skinny-1.20.2-py36hf25f7b9_0.tar.bz2
linux-ppc64le/mlflow-skinny-1.20.2-py37h34dc811_0.tar.bz2
linux-ppc64le/mlflow-skinny-1.20.2-py38h16f897f_0.tar.bz2
linux-ppc64le/mlflow-skinny-1.20.2-py39h4c20f0a_0.tar.bz2
linux-ppc64le/mlflow-ui-dbg-1.20.2-py36ha29011c_0.tar.bz2
linux-ppc64le/mlflow-ui-dbg-1.20.2-py37h1717c74_0.tar.bz2
linux-ppc64le/mlflow-ui-dbg-1.20.2-py38hf366367_0.tar.bz2
linux-ppc64le/mlflow-ui-dbg-1.20.2-py39ha92320b_0.tar.bz2
linux-ppc64le/nauty-2.7.3-h4e0d66e_0.tar.bz2
linux-ppc64le/nbgrader-0.6.2-py36h270354c_0.tar.bz2
linux-ppc64le/nbgrader-0.6.2-py37h35e4cab_0.tar.bz2
linux-ppc64le/nbgrader-0.6.2-py38hf8b3453_0.tar.bz2
linux-ppc64le/nbgrader-0.6.2-py39hc1b9086_0.tar.bz2
linux-ppc64le/nss-3.70-ha04f6ab_0.tar.bz2
linux-ppc64le/numpy-stl-2.16.3-py36h97d1520_0.tar.bz2
linux-ppc64le/numpy-stl-2.16.3-py37h290ce0f_0.tar.bz2
linux-ppc64le/numpy-stl-2.16.3-py37h56ea505_0.tar.bz2
linux-ppc64le/numpy-stl-2.16.3-py38h3ba5731_0.tar.bz2
linux-ppc64le/numpy-stl-2.16.3-py39h50b74dd_0.tar.bz2
linux-ppc64le/petsc4py-3.15.1-complex_h2e6291c_0.tar.bz2
linux-ppc64le/petsc4py-3.15.1-complex_h571f9b0_0.tar.bz2
linux-ppc64le/petsc4py-3.15.1-complex_h6d953cb_0.tar.bz2
linux-ppc64le/petsc4py-3.15.1-complex_h7473499_0.tar.bz2
linux-ppc64le/petsc4py-3.15.1-complex_h76ca59d_0.tar.bz2
linux-ppc64le/petsc4py-3.15.1-complex_h9935aae_0.tar.bz2
linux-ppc64le/petsc4py-3.15.1-complex_h9e59b48_0.tar.bz2
linux-ppc64le/petsc4py-3.15.1-complex_hb2902ad_0.tar.bz2
linux-ppc64le/petsc4py-3.15.1-complex_hbaf5487_0.tar.bz2
linux-ppc64le/petsc4py-3.15.1-complex_hbdf4c12_0.tar.bz2
linux-ppc64le/petsc4py-3.15.1-real_h1d2f542_100.tar.bz2
linux-ppc64le/petsc4py-3.15.1-real_h4768410_100.tar.bz2
linux-ppc64le/petsc4py-3.15.1-real_h49c9e13_100.tar.bz2
linux-ppc64le/petsc4py-3.15.1-real_h66010f8_100.tar.bz2
linux-ppc64le/petsc4py-3.15.1-real_h6b50bbd_100.tar.bz2
linux-ppc64le/petsc4py-3.15.1-real_h7330e61_100.tar.bz2
linux-ppc64le/petsc4py-3.15.1-real_h865e01f_100.tar.bz2
linux-ppc64le/petsc4py-3.15.1-real_h90bb8e8_100.tar.bz2
linux-ppc64le/petsc4py-3.15.1-real_hc3d6445_100.tar.bz2
linux-ppc64le/petsc4py-3.15.1-real_he873264_100.tar.bz2
linux-ppc64le/proj-8.1.1-h7148cf8_1.tar.bz2
linux-ppc64le/promise-2.3-py36h270354c_3.tar.bz2
linux-ppc64le/py-spy-0.3.9-h9b295ce_0.tar.bz2
linux-ppc64le/pyproj-3.2.0-py37h32a5595_0.tar.bz2
linux-ppc64le/pyproj-3.2.0-py37h549bcde_0.tar.bz2
linux-ppc64le/pyproj-3.2.0-py37hd2bd4fb_0.tar.bz2
linux-ppc64le/pyproj-3.2.0-py37hfc8484e_0.tar.bz2
linux-ppc64le/pyproj-3.2.0-py38h076e4c5_0.tar.bz2
linux-ppc64le/pyproj-3.2.0-py38h088fb19_0.tar.bz2
linux-ppc64le/pyproj-3.2.0-py39h1e64159_0.tar.bz2
linux-ppc64le/pyproj-3.2.0-py39ha67f3c8_0.tar.bz2
linux-ppc64le/python-3.6.13-h57873ef_1_cpython.tar.bz2
linux-ppc64le/python-3.9.6-h57873ef_2_cpython.tar.bz2
linux-ppc64le/pythran-0.10.0-py36h416786f_0.tar.bz2
linux-ppc64le/pythran-0.10.0-py37h50ba158_0.tar.bz2
linux-ppc64le/pythran-0.10.0-py37heb9fb97_0.tar.bz2
linux-ppc64le/pythran-0.10.0-py38h188d082_0.tar.bz2
linux-ppc64le/pythran-0.10.0-py39h31502c1_0.tar.bz2
linux-ppc64le/r-lhs-1.1.2-r40h6203a36_0.tar.bz2
linux-ppc64le/r-lhs-1.1.2-r41h6203a36_0.tar.bz2
linux-ppc64le/r-lhs-1.1.3-r40h6203a36_0.tar.bz2
linux-ppc64le/r-lhs-1.1.3-r41h6203a36_0.tar.bz2
linux-ppc64le/r-officer-0.4.0-r40h6203a36_0.tar.bz2
linux-ppc64le/r-officer-0.4.0-r41h6203a36_0.tar.bz2
linux-ppc64le/r-spdep-1.1_11-r40hb2931de_0.tar.bz2
linux-ppc64le/r-spdep-1.1_11-r41hb2931de_0.tar.bz2
linux-ppc64le/r-stringdist-0.9.8-r40h2be38b1_0.tar.bz2
linux-ppc64le/r-stringdist-0.9.8-r41h2be38b1_0.tar.bz2
linux-ppc64le/r-tzdb-0.1.2-r40h6203a36_0.tar.bz2
linux-ppc64le/r-vroom-1.5.4-r40h6203a36_0.tar.bz2
linux-ppc64le/r-vroom-1.5.4-r41h6203a36_0.tar.bz2
linux-ppc64le/rapidfuzz-1.5.0-py36h08d3667_0.tar.bz2
linux-ppc64le/rapidfuzz-1.5.0-py37hc9b93fd_0.tar.bz2
linux-ppc64le/rapidfuzz-1.5.0-py37hfc837b7_0.tar.bz2
linux-ppc64le/rapidfuzz-1.5.0-py38ha35a538_0.tar.bz2
linux-ppc64le/rapidfuzz-1.5.0-py39had50986_0.tar.bz2
linux-ppc64le/reproject-0.8-py37h56ea505_0.tar.bz2
linux-ppc64le/reproject-0.8-py39h50b74dd_0.tar.bz2
linux-ppc64le/ruby-2.5.7-ha4e8978_3.tar.bz2
linux-ppc64le/ruby-2.6.6-ha4e8978_3.tar.bz2
linux-ppc64le/ruby-2.7.2-ha4e8978_4.tar.bz2
linux-ppc64le/rust-1.55.0-h978bb50_0.tar.bz2
linux-ppc64le/scikit-build-0.12.0-py36h08d3667_0.tar.bz2
linux-ppc64le/scikit-build-0.12.0-py37hc9b93fd_0.tar.bz2
linux-ppc64le/scikit-build-0.12.0-py38ha35a538_0.tar.bz2
linux-ppc64le/scikit-build-0.12.0-py39had50986_0.tar.bz2
linux-ppc64le/scikit-learn-0.24.2-py36hd9e8007_1.tar.bz2
linux-ppc64le/scikit-learn-0.24.2-py37h0208604_1.tar.bz2
linux-ppc64le/scikit-learn-0.24.2-py37hfdb2fe0_1.tar.bz2
linux-ppc64le/scikit-learn-0.24.2-py38h463af93_1.tar.bz2
linux-ppc64le/scikit-learn-0.24.2-py39hd71ca89_1.tar.bz2
linux-ppc64le/setuptools-57.5.0-py37hadc05a3_0.tar.bz2
linux-ppc64le/setuptools-58.0.0-py37hadc05a3_0.tar.bz2
linux-ppc64le/setuptools-58.0.2-py36h270354c_0.tar.bz2
linux-ppc64le/setuptools-58.0.2-py37h35e4cab_0.tar.bz2
linux-ppc64le/setuptools-58.0.2-py37hadc05a3_0.tar.bz2
linux-ppc64le/setuptools-58.0.2-py38hf8b3453_0.tar.bz2
linux-ppc64le/setuptools-58.0.2-py39hc1b9086_0.tar.bz2
linux-ppc64le/setuptools-58.0.3-py36h270354c_0.tar.bz2
linux-ppc64le/setuptools-58.0.3-py37h35e4cab_0.tar.bz2
linux-ppc64le/setuptools-58.0.3-py37hadc05a3_0.tar.bz2
linux-ppc64le/setuptools-58.0.3-py38hf8b3453_0.tar.bz2
linux-ppc64le/setuptools-58.0.3-py39hc1b9086_0.tar.bz2
linux-ppc64le/setuptools-58.0.4-py36h270354c_0.tar.bz2
linux-ppc64le/setuptools-58.0.4-py37h35e4cab_0.tar.bz2
linux-ppc64le/setuptools-58.0.4-py37hadc05a3_0.tar.bz2
linux-ppc64le/setuptools-58.0.4-py38hf8b3453_0.tar.bz2
linux-ppc64le/setuptools-58.0.4-py39hc1b9086_0.tar.bz2
linux-ppc64le/snowflake-connector-python-2.6.0-py36h1fa9092_1.tar.bz2
linux-ppc64le/snowflake-connector-python-2.6.0-py39haecda89_1.tar.bz2
linux-ppc64le/sqlite-3.36.0-h4e2196e_1.tar.bz2
linux-ppc64le/thinc-8.0.10-py36h5b6f827_0.tar.bz2
linux-ppc64le/thinc-8.0.10-py37hab213b1_0.tar.bz2
linux-ppc64le/thinc-8.0.10-py38h62afdde_0.tar.bz2
linux-ppc64le/thinc-8.0.10-py39h31502c1_0.tar.bz2
linux-ppc64le/thinc-8.0.9-py36h5b6f827_0.tar.bz2
linux-ppc64le/thinc-8.0.9-py37hab213b1_0.tar.bz2
linux-ppc64le/thinc-8.0.9-py39h31502c1_0.tar.bz2
linux-ppc64le/tiledb-2.4.0-h030908f_0.tar.bz2
linux-ppc64le/uproot-4.1.1-py36h270354c_1.tar.bz2
linux-ppc64le/uproot-4.1.1-py37h35e4cab_1.tar.bz2
linux-ppc64le/uproot-4.1.1-py37hadc05a3_1.tar.bz2
linux-ppc64le/uproot-4.1.1-py38hf8b3453_1.tar.bz2
linux-ppc64le/uproot-4.1.1-py39hc1b9086_1.tar.bz2
linux-ppc64le/vim-8.2.3404-py36h652fc3f_1.tar.bz2
linux-ppc64le/vim-8.2.3404-py37h0c9c7fd_1.tar.bz2
linux-ppc64le/vim-8.2.3404-py37h519257b_1.tar.bz2
linux-ppc64le/vim-8.2.3404-py38h26a541b_1.tar.bz2
linux-ppc64le/vim-8.2.3404-py39h9bd833a_1.tar.bz2
linux-ppc64le/websockets-10.0-py37h0630641_0.tar.bz2
linux-ppc64le/websockets-10.0-py37h6642d69_0.tar.bz2
linux-ppc64le/websockets-10.0-py38h98b8a6f_0.tar.bz2
linux-ppc64le/websockets-10.0-py39ha810350_0.tar.bz2
linux-ppc64le/westpa-2020.05-py36h7bd6e92_0.tar.bz2
linux-ppc64le/westpa-2020.05-py36hc33305d_0.tar.bz2
linux-ppc64le/westpa-2020.05-py37h533c26d_0.tar.bz2
linux-ppc64le/westpa-2020.05-py37h6642d69_0.tar.bz2
linux-ppc64le/westpa-2020.05-py38h69e6286_0.tar.bz2
linux-ppc64le/westpa-2020.05-py38h98b8a6f_0.tar.bz2
linux-ppc64le/xeus-robot-0.3.8-py37hf41d104_0.tar.bz2
linux-ppc64le/xeus-robot-0.3.8-py38h7011a58_0.tar.bz2
linux-ppc64le/xeus-robot-0.3.8-py39h1f10ff4_0.tar.bz2
linux-ppc64le/xtensor-io-0.12.9-h2acdbc0_0.tar.bz2
linux-ppc64le/zfp-0.5.5-h3b9df90_6.tar.bz2
linux-ppc64le/zfpy-0.5.5-py36h5cfb26e_6.tar.bz2
linux-ppc64le/zfpy-0.5.5-py37h0eb6cc8_6.tar.bz2
linux-ppc64le/zfpy-0.5.5-py37had80f8f_6.tar.bz2
linux-ppc64le/zfpy-0.5.5-py38hca0025d_6.tar.bz2
linux-ppc64le/zfpy-0.5.5-py39h6474468_6.tar.bz2
""".splitlines()


def split_pkg(pkg: str):
    """Split a package filename into its components.

    Parameters
    ----------
    pkg : str
        The package filename.

    Returns
    -------
    tuple[str, str, str, str]
        The platform, package name, version, and build string.


    Raises
    ------
    RuntimeError
        If the package filename does not end with ".tar.bz2".
    """
    if not pkg.endswith(".tar.bz2"):
        raise RuntimeError("Can only process packages that end in .tar.bz2")
    pkg = pkg[:-8]
    plat, pkg_name = pkg.split("/")
    name_ver, build = pkg_name.rsplit("-", 1)
    name, ver = name_ver.rsplit("-", 1)
    return plat, name, ver, build


class RebuildBroken(Migrator):
    migrator_version = 3
    rerender = False
    bump_number = 1

    """Migrator for rebuilding packages marked as broken.

    Parameters
    ----------
    outputs_lut : dict
        Mapping to get feedstocks from outputs.
    pr_limit : int, optional
        The maximum number of PRs made per run of the bot.
    """

    def __init__(
        self,
        *,
        pr_limit: int = 0,
        total_graph: nx.DiGraph | None = None,
        graph: nx.DiGraph | None = None,
        effective_graph: nx.DiGraph | None = None,
    ):
        if not hasattr(self, "_init_args"):
            self._init_args = []

        if not hasattr(self, "_init_kwargs"):
            self._init_kwargs = {
                "pr_limit": pr_limit,
                "graph": graph,
                "effective_graph": effective_graph,
                "total_graph": total_graph,
            }

        self.name = "rebuild-broken"

        outputs_to_migrate = {split_pkg(pkg)[1] for pkg in BROKEN_PACKAGES}
        self.feedstocks_to_migrate = set()
        outputs_lut = get_outputs_lut(total_graph, graph, effective_graph)
        for output in outputs_to_migrate:
            for fs in outputs_lut.get(output, {output}):
                self.feedstocks_to_migrate |= {fs}

        super().__init__(
            pr_limit=pr_limit,
            check_solvable=False,
            graph=graph,
            effective_graph=effective_graph,
            total_graph=total_graph,
        )

    def order(
        self,
        graph: nx.DiGraph,
        total_graph: nx.DiGraph,
    ):
        return sorted(list(graph.nodes), key=lambda x: RNG.random())

    def filter_not_in_migration(self, attrs, not_bad_str_start=""):
        if super().filter_not_in_migration(attrs, not_bad_str_start):
            return True

        not_broken = attrs["feedstock_name"] not in self.feedstocks_to_migrate
        return not_broken

    def migrate(self, recipe_dir, attrs, **kwargs):
        self.set_build_number(os.path.join(recipe_dir, "meta.yaml"))
        return super().migrate(recipe_dir, attrs)

    def pr_body(self, feedstock_ctx: ClonedFeedstockContext) -> str:
        body = super().pr_body(feedstock_ctx)
        body = body.format(
            """\
One or more outputs of this feedstock were marked broken due a security
issue with Travis-CI. Please Merge this PR to rebuild the packages from this
feedstock. Thank you!""",
        )
        return body

    def commit_message(self, feedstock_ctx) -> str:
        return "rebuild for output marked as broken"

    def pr_title(self, feedstock_ctx) -> str:
        return "Rebuild for output marked broken"

    def remote_branch(self, feedstock_ctx) -> str:
        return f"{self.name}-migration-{self.migrator_version}"

    def migrator_uid(self, attrs):
        n = super().migrator_uid(attrs)
        n["name"] = self.name
        return n

FROM mcr.microsoft.com/vscode/devcontainers/miniconda:0-3

# [Choice] Node.js version: none, lts, 16, 14, 12, 10
ARG NODE_VERSION="none"
RUN if [ "${NODE_VERSION}" != "none" ]; then su vscode -c "umask 0002 && . /usr/local/share/nvm/nvm.sh && nvm install ${NODE_VERSION} 2>&1"; fi

COPY requirements/* /tmp/conda-tmp/

RUN /opt/conda/bin/conda install -c conda-forge -n base mamba
RUN /opt/conda/bin/mamba install -c conda-forge -n base --file /tmp/conda-tmp//run --file /tmp/conda-tmp//test

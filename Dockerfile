FROM quay.io/condaforge/linux-anvil-cos7-x86_64:latest

ENV AUTOTICK_BOT_DIR=/opt/autotick-bot
COPY . $AUTOTICK_BOT_DIR
RUN $AUTOTICK_BOT_DIR/docker/install_cmds

# put in new entrypoint
RUN cp -f $AUTOTICK_BOT_DIR/docker/entrypoint /opt/docker/bin/entrypoint

# made at runtime by the bot for data
ENV TMPDIR=/tmp
RUN useradd --shell /bin/bash -c "" -m conda
ENV HOME=/home/conda
ENV USER=conda
ENV LOGNAME=conda
ENV MAIL=/var/spool/mail/conda
ENV PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/home/conda/bin
RUN chown conda:conda $HOME && \
    cp -R /etc/skel $HOME && \
    chown -R conda:conda $HOME/skel && \
    (ls -A1 $HOME/skel | xargs -I {} mv -n $HOME/skel/{} $HOME) && \
    rm -Rf $HOME/skel && \
    cd $HOME && \
    /bin/bash -l -c "conda activate cf-scripts"
USER conda

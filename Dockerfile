FROM quay.io/condaforge/linux-anvil-cos7-x86_64:latest

ENV AUTOTICK_BOT_DIR=/opt/autotick-bot
COPY . $AUTOTICK_BOT_DIR
RUN cat $AUTOTICK_BOT_DIR/docker/entrypoint_source >> /opt/docker/bin/entrypoint_source
RUN $AUTOTICK_BOT_DIR/docker/install_cmds

FROM quay.io/condaforge/linux-anvil-cos7-x86_64:latest

ENV AUTOTICK_BOT_DIR=/opt/autotick-bot
COPY . $AUTOTICK_BOT_DIR
RUN $AUTOTICK_BOT_DIR/docker/install_cmds

# put in new entrypoint
RUN cp -f $AUTOTICK_BOT_DIR/docker/entrypoint /opt/docker/bin/entrypoint

# made at runtime by the bot for data
ENV TMPDIR=/tmp

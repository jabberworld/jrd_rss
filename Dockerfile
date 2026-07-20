FROM debian:11-slim
RUN useradd -u 270 -U -d /app -m py2soft
RUN apt-get update && apt-get install -y --no-install-recommends python2-minimal libmariadb3 libpython2.7 libjpeg62-turbo libimagequant0 libtiff5 libxslt1.1 netbase ca-certificates
USER py2soft
WORKDIR /app
STOPSIGNAL SIGQUIT
ENV PYTHONUNBUFFERED=1

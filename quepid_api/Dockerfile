FROM python:3.12 AS app

WORKDIR /app

ENV TMP_DIR=/tmp/app
ENV TORCH_HOME=/tmp/app/torch
ENV PLAYWRIGHT_BROWSERS_PATH=/tmp/app/plwr

RUN mkdir ${TMP_DIR} -p && \
    chmod 0777 ${TMP_DIR} -R

CMD ["uwsgi"]

VOLUME [ "${TMP_DIR}" ]

RUN apt-get update
RUN apt-get install -y python3-dev default-libmysqlclient-dev build-essential
RUN apt-get install -y libnss3 libnspr4 libdbus-1-3 libatk1.0-0 libatk-bridge2.0-0 libatspi2.0-0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 libdrm2 libxkbcommon0 libasound2

COPY ./requirements.txt ./
RUN pip install -r requirements.txt
RUN playwright install chromium

COPY . ./

RUN ./manage.py collectstatic --noinput

RUN chown -R www-data:www-data .

ENV TZ=Europe/Amsterdam
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

USER www-data:www-data

FROM nginx:mainline-alpine AS web

RUN apk add --no-cache tzdata
ENV TZ Europe/Amsterdam

COPY --from=app /app/static /usr/share/nginx/html/static
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf

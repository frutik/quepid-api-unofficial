FROM python:3.12 AS app

WORKDIR /app/quepid_api

ENV TMP_DIR=/tmp/app
ENV TORCH_HOME=/tmp/app/torch

RUN mkdir ${TMP_DIR} -p && \
    chmod 0777 ${TMP_DIR} -R

CMD ["uwsgi"]

VOLUME [ "${TMP_DIR}" ]

RUN apt-get update
RUN apt-get install -y python3-dev default-libmysqlclient-dev build-essential

COPY ./requirements.txt ./
RUN pip install -r requirements.txt

COPY . ./

RUN ./quepid_api/manage.py collectstatic --noinput

RUN chown -R www-data:www-data .

ENV TZ=Europe/Amsterdam
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

USER www-data:www-data

FROM nginx:mainline-alpine AS web

RUN apk add --no-cache tzdata
ENV TZ Europe/Amsterdam

COPY --from=app /app/quepid_api/static /usr/share/nginx/html/static
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf

FROM python:3.10-alpine
ENV PYTHONUNBUFFERED=1
RUN mkdir /etc/modbusRTU/
WORKDIR /etc/modbusRTU/
RUN apk add build-base && \
  apk add git && \
  git clone https://github.com/doanhkem/modbusRTU.git /etc/modbusRTU/ && \
  pip install 'asyncio' 'pymodbus==2.5.2' 'aioredis==1.3.1' 'paho-mqtt' && \
  apk del build-base linux-headers pcre-dev openssl-dev && \
  rm -rf /var/cache/apk/*
CMD ["python", "appConnectivity.py"]
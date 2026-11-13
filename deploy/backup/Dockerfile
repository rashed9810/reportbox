FROM postgres:16-alpine
RUN apk add --no-cache openssl
COPY backup.sh /backup.sh
RUN chmod +x /backup.sh
ENTRYPOINT ["/backup.sh"]

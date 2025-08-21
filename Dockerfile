FROM --platform=linux/amd64 python:3.11.12-alpine3.21

WORKDIR /app

COPY --chown=python:python requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=python:python . .

RUN chmod +x entrypoint.sh

ENTRYPOINT [ "/app/entrypoint.sh" ]
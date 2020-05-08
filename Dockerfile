FROM python:3.8-alpine
WORKDIR /app
ARG TRAVIS_BRANCH=$TRAVIS_BRANCH
ENV LC_ALL=C.UTF-8
ENV LANG=C.UTF-8
# Install necessary software
RUN apk update && apk upgrade
RUN apk add --no-cache build-base git ffmpeg openssl-dev libffi-dev
RUN pip install poetry
# Copy in app files
ADD . .
# Create out directory
RUN mkdir /app/out
# Create poetry venv
RUN poetry install
ENTRYPOINT ["poetry", "run", "python3", "streamdl.py", "-o", "/app/out", "-c", "config.yml", "-r", "$REPEAT_TIME", "-l", "stdout", "-ll", "$LOG_LEVEL"]

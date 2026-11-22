FROM docker:cli

RUN apk add --no-cache python3 py3-flask py3-psutil py3-yaml py3-rich

ENV PYTHONDONTWRITEBYTECODE=1

CMD ["python3", "/source/status/main.py"]

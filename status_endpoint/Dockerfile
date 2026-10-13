FROM docker:cli

RUN apk add --no-cache python3 py3-psutil py3-pyyaml py3-rich

ENV PYTHONDONTWRITEBYTECODE=1

CMD ["python3", "/source/status_endpoint/main.py"]

FROM mcr.microsoft.com/playwright/python:v1.63.0-noble

WORKDIR /workspace

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

ENTRYPOINT ["python", "runner/playwright_runner.py"]
CMD ["--help"]

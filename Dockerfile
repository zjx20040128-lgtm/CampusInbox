FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY courseinbox ./courseinbox
COPY server.py .
COPY web ./web
COPY scripts/windows-ocr.ps1 ./scripts/windows-ocr.ps1
RUN useradd -m courseinbox && mkdir /app/data && chown -R courseinbox:courseinbox /app
USER courseinbox
VOLUME ["/app/data"]
EXPOSE 8765
CMD ["python", "server.py", "--host", "0.0.0.0", "--port", "8765"]

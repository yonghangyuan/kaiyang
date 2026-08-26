Start-Process -WindowStyle Hidden -FilePath python -ArgumentList '-m','uvicorn','kaiyang.main:app','--host','127.0.0.1','--port','8721','--log-level','warning' -WorkingDirectory 'F:\kaiyang'

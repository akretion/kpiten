FROM python:3.14.4-bookworm
WORKDIR /kpiten
EXPOSE 5000
COPY ./requirement.txt .
RUN pip install uv && uv venv && . .venv/bin/activate
RUN uv pip install -r requirement.txt
ENV PYTHONPATH=/kpiten/
COPY . /kpiten/
ENTRYPOINT [ "uv", "run", "main.py" ]
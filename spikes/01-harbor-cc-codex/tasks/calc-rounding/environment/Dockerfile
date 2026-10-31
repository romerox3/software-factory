FROM python:3.12-slim
RUN pip install --no-cache-dir pytest==8.3.3
WORKDIR /workspace
COPY repo/ /workspace/
RUN git --version >/dev/null 2>&1 || (apt-get update -qq && apt-get install -y -qq git >/dev/null)
RUN git init -q && git add -A && git -c user.email=f@f -c user.name=f commit -qm base

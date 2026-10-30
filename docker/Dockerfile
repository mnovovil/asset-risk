# The whole app in one image. Build from the repo root, or use script/start.sh:
#   docker build -f docker/Dockerfile -t asset-risk .
# Settings are not in the image (Terraform's output can hold AWS keys): compose mounts them.
FROM node:24-slim AS front
WORKDIR /build/app/front
COPY app/front/package.json app/front/package-lock.json ./
RUN npm ci
COPY app/front/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/home/app \
    ASSET_RISK_CONFIG=/config/.asset-risk.json \
    GEOLOCATE_CONFIG=/config/.geolocate.json \
    ASSET_RISK_DATA_DIR=/data

RUN useradd --create-home --home-dir /home/app --uid 1000 app

COPY requirements.txt /srv/requirements.txt
RUN pip install --no-cache-dir -r /srv/requirements.txt

# Bake the DuckDB extensions in, so runs need the network only for S3. Any --user UID must be able
# to read them, because the container runs as the host user in order to read the mounted settings.
RUN python -c "import duckdb; c = duckdb.connect(); c.install_extension('spatial'); c.install_extension('httpfs')" \
    && chmod -R a+rwX /home/app

COPY app/engine/ /srv/app/engine/
COPY vendor/geolocate/src/ /srv/vendor/geolocate/src/
COPY script/serve.py /srv/script/serve.py
COPY --from=front /build/app/front/dist/ /srv/app/front/dist/

# A new named volume takes this folder's mode, which lets any --user UID write to it.
RUN mkdir /data && chmod 1777 /data

USER app
WORKDIR /srv
EXPOSE 8000
ENTRYPOINT ["python", "/srv/script/serve.py", "--host", "0.0.0.0", "--port", "8000"]

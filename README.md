## Docker Hub Link
[link](https://hub.docker.com/r/jian0209/k8s-post-deploy-task)

## Build and deploy
```https://hub.docker.com/r/jian0209/k8s-post-deploy-task
tag=v1.0.0
# deploy to docker hub
docker login -u <username> --password-stdin < xxx.txt

docker buildx build \
  --platform linux/amd64,linux/arm64 \
  --push \
  -t <username>/$image_name:$tag \
  -t <username>/$image_name:latest \
  .
```
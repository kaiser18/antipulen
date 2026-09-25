$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker is not installed or is not available on PATH."
}

if (-not (Test-Path ".env")) {
    throw "Missing .env file. Copy .env.example to .env and set DISCORD_TOKEN."
}

$imageName = "antipulen-bot"
$containerName = "antipulen-bot"

docker build --tag $imageName .
docker rm --force $containerName 2>$null
docker run --rm --name $containerName --env-file .env $imageName

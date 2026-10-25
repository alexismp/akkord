# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Stage 1: Build the native Rust PDF layout & vector annotation engine
FROM rust:1-bookworm AS rust-builder
WORKDIR /build/rust-engine
COPY rust-engine/Cargo.toml rust-engine/Cargo.lock* ./
COPY rust-engine/src ./src
RUN cargo build --release

# Stage 2: Build the Go HTTP server, batch worker pool & CLI orchestrator
FROM golang:1.23-bookworm AS go-builder
WORKDIR /build
COPY go.mod ./
COPY cmd ./cmd
COPY internal ./internal
RUN CGO_ENABLED=0 GOOS=linux go build -ldflags="-s -w" -o /build/akkord ./cmd/akkord

# Stage 3: Minimal production runtime image (~35 MB + poppler-utils)
FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    poppler-utils \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

ENV PORT=8080 \
    AKKORD_OUTPUT_DIR=/tmp/akkord_outputs \
    AKKORD_RUST_ENGINE_BIN=/usr/local/bin/akkord-pdf-engine

WORKDIR /app
COPY --from=rust-builder /build/rust-engine/target/release/akkord-pdf-engine /usr/local/bin/akkord-pdf-engine
COPY --from=go-builder /build/akkord /usr/local/bin/akkord
COPY akkord/static ./akkord/static

EXPOSE 8080
CMD ["/usr/local/bin/akkord", "serve"]

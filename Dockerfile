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

# Stage 1: Build the Modern Java 25 shaded JAR with Maven
FROM eclipse-temurin:25-jdk AS builder
RUN apt-get update && apt-get install -y --no-install-recommends maven && rm -rf /var/lib/apt/lists/*
WORKDIR /build
COPY pom.xml .
COPY src ./src
RUN mvn -B package -DskipTests

# Stage 2: Standard OpenJDK 25 JRE runtime (without GraalVM) + AppCDS & ZGC + Compact Object Headers
FROM eclipse-temurin:25-jre
ENV PORT=8080 \
    AKKORD_OUTPUT_DIR=/tmp/akkord_outputs \
    JAVA_TOOL_OPTIONS="-XX:+UseZGC -XX:+UseCompactObjectHeaders -Djava.awt.headless=true"

WORKDIR /app
COPY --from=builder /build/target/akkord.jar /app/akkord.jar
COPY akkord/static /app/akkord/static

# Pre-generate Application Class-Data Sharing (AppCDS) archive for fast standard JVM cold starts
RUN java -XX:ArchiveClassesAtExit=/app/akkord-cds.jsa --version || true

EXPOSE 8080
CMD ["java", "-XX:SharedArchiveFile=/app/akkord-cds.jsa", "-jar", "/app/akkord.jar", "serve"]

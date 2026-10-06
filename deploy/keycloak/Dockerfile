# Keycloak for the pilot (#57): build options baked in, so pods start with `start --optimized`.
#   docker build -t <registry>/smart-tutor/keycloak:<sha> deploy/keycloak
# Runtime options (hostname, database, secrets) come from the keycloak chart. Same version as compose.yaml.
FROM quay.io/keycloak/keycloak:26.3 AS builder
ENV KC_DB=postgres \
    KC_HEALTH_ENABLED=true \
    KC_HTTP_RELATIVE_PATH=/auth
RUN /opt/keycloak/bin/kc.sh build

FROM quay.io/keycloak/keycloak:26.3
COPY --from=builder /opt/keycloak/ /opt/keycloak/
ENTRYPOINT ["/opt/keycloak/bin/kc.sh"]

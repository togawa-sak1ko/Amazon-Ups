# Danger Log

## Open risks

1. We now have retry logic for missed world ACKs, but it still needs live validation under actual world flakiness and disconnect scenarios. Unit tests cover the timeout path, but the real simulator is the final proof.
2. The HTTP protocol is implemented on both inbound and outbound UPS paths, but we still need full end-to-end interoperability testing with the Mini-Amazon team in a shared deployment.
3. Redirect boundary cases are still sensitive to timing. A redirect request arriving near the same time as a load or delivery transition could still expose race conditions that only appear in live integration.
4. Package identity must stay consistent across Amazon, UPS, and the world. We preserve both `package_id` and a user-facing `tracking_number`, but mixed or stale test data could still create confusing behavior during demos.
5. The Docker stack still starts the daemon in dry-run mode by default and does not launch a world simulator container. The final deployment procedure must explicitly override that or use a separate live-world setup.
6. Host, port, and world ID values are runtime configuration, not fixed constants. Before any joint test or demo, UPS and Amazon need to agree on the actual UPS host, world host, and active world ID.
7. If Amazon callback delivery fails even after HTTP retry attempts, UPS currently records the failure in shipment events but does not persist a separate callback replay queue. Recovery would be partly manual.
8. The full Django test suite can still fail in environments that are missing the protobuf runtime dependency, even though the generated bindings are present in the repo. Deployment setup must include that dependency explicitly.
9. The daemon and web app share the same database state, so stale local data or mock seed data can interfere with integration testing if the environment is not reset cleanly between runs.
10. Our strongest differentiated features, especially account-linked shipment ownership and redirect behavior, depend on the Mini-Amazon side sending the agreed protocol fields consistently. A mismatch there would make the UPS UI look broken even if the UPS code is correct.

extern int ken_namespace_marker(void);
int ken_namespace_bridge(void) { return ken_namespace_marker() + 1; }

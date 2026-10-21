# Pinned native import of the checksum-pinned MLX0.32.3 wheel core.
# The wheel export contains SDK paths from its upstream build host.
add_library(mlx SHARED IMPORTED)
set_target_properties(mlx PROPERTIES IMPORTED_LOCATION "$ENV{KEN_MLX_CORE}/lib/libmlx.dylib" INTERFACE_INCLUDE_DIRECTORIES "$ENV{KEN_MLX_CORE}/include" INTERFACE_COMPILE_OPTIONS "-DACCELERATE_NEW_LAPACK;-D_METAL_")
set(MLX_FOUND TRUE)

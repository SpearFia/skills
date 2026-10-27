# OFX plugin skeleton. Copy into <plugin>/ofx/ and rename.
cmake_minimum_required(VERSION 3.24)
project(spearfia_plugin_ofx VERSION 0.1.0 LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 17)

set(OFX_SDK_DIR "C:/dev/sdks/openfx" CACHE PATH "OpenFX SDK root")
add_library(plugin MODULE src/plugin.cpp)
target_include_directories(plugin PRIVATE "${OFX_SDK_DIR}/include" "${OFX_SDK_DIR}/Support/include")
set_target_properties(plugin PROPERTIES PREFIX "" SUFFIX ".ofx")
# TODO: link the OFX Support library and lay out the .ofx.bundle folder on install.

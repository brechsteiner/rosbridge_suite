cmake_minimum_required(VERSION 3.5)
project(rosbridge_gateway)

find_package(ament_cmake_ros REQUIRED)
find_package(ament_cmake_core REQUIRED)
find_package(ament_cmake_python REQUIRED)

ament_python_install_package(
  ${PROJECT_NAME} PACKAGE_DIR "src/${PROJECT_NAME}")

ament_package()

install(PROGRAMS
  scripts/rosbridge_gateway.py
  scripts/rosbridge_gateway
  DESTINATION lib/${PROJECT_NAME}
)

install(FILES
  launch/rosbridge_gateway_launch.xml
  DESTINATION share/${PROJECT_NAME}/launch
)

if(BUILD_TESTING)
  find_package(launch_testing_ament_cmake REQUIRED)
endif()

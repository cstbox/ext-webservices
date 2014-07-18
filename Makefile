# CSTBox framework
#
# Makefile for building the Debian distribution package containing the
# Web services base infrastructure.
#
# author = Eric PASCUAL - CSTB (eric.pascual@cstb.fr)

# name of the CSTBox module
MODULE_NAME=ext-webservices

include $(CSTBOX_DEVEL_HOME)/lib/makefile-dist.mk

copy_files: \
	copy_bin_files \
	copy_python_files \
	copy_init_scripts\
	copy_etc_files


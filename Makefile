# algomaschine-kit: `make new NAME=my_idea [DIR=~/projects]` starts a project from templates/project;
# `make install-skills` makes the Claude Code skills available in every project.
KIT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
DIR ?= $(HOME)/projects
.PHONY: new install-skills help
help:
	@echo "make new NAME=<name> [DIR=$(DIR)]   start a project"; echo "make install-skills               copy skills/ to ~/.claude/skills"
new:
	@test -n "$(NAME)" || { echo "usage: make new NAME=my_idea"; exit 1; }
	@test ! -e $(DIR)/$(NAME) || { echo "$(DIR)/$(NAME) exists"; exit 1; }
	mkdir -p $(DIR) && cp -r $(KIT)/templates/project $(DIR)/$(NAME)
	sed -i "s|^KIT ?=.*|KIT ?= $(KIT)|" $(DIR)/$(NAME)/Makefile
	sed -i "s|__NAME__|$(NAME)|g" $(DIR)/$(NAME)/config.toml $(DIR)/$(NAME)/SPEC.md $(DIR)/$(NAME)/IDEA.md
	cd $(DIR)/$(NAME) && git init -q -b main && git add -A && \
	  { git commit -q -m "new AlgoMaschine project $(NAME)" 2>/dev/null || \
	    git -c user.name="$${GIT_AUTHOR_NAME:-AlgoMaschine}" -c user.email="$${GIT_AUTHOR_EMAIL:-kit@localhost}" commit -q -m "new AlgoMaschine project $(NAME)"; }
	@echo "created $(DIR)/$(NAME): fill IDEA.md, then ask Claude to use the quant-idea-to-system skill"
install-skills:
	mkdir -p $(HOME)/.claude/skills && cp -r $(KIT)/skills/* $(HOME)/.claude/skills/
	@ls $(HOME)/.claude/skills

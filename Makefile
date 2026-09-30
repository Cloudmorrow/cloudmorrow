# Releasing Cloudmorrow and deploying what we run. `make deploy` shows what
# is where and offers a menu; scripts/deploy.py says the rest.
#
#   make deploy                            status, then a menu
#   make deploy WHAT=explain               how versions fit together
#   make deploy WHAT=release BUMP=patch    (minor unless BUMP says major or patch)
#   make deploy WHAT=website YES=1         without asking

WHAT ?=
BUMP ?= minor
YES ?=

.PHONY: deploy status

deploy:
	@python3 scripts/deploy.py $(WHAT) --bump $(BUMP) $(if $(YES),--yes)

status:
	@python3 scripts/deploy.py status

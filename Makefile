.PHONY: test clean default

default:
	pyinstaller -c gira.py
	rm -rf ${HOME}/bin/gira && ln -s ${PWD}/dist/gira/gira ${HOME}/bin/gira

clean:
	@rm -rf __pycache__ build dist


test:
	python gira.py runtests all

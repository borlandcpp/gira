.PHONY: test clean default

default:
	pyinstaller -c gira.py
	rm -f /usr/local/bin/gira && ln -s ${PWD}/dist/gira/gira /usr/local/bin/gira

clean:
	@rm -rf __pycache__ build dist


test:
	python gira.py runtests all

default:
	pyinstaller -c -F gira.py
	cp dist/gira ${HOME}/bin && chmod a+x ${HOME}/bin/gira

clean:
	@rm -rf __pycache__ build dist

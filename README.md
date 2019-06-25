Cassie
==
Python XMPP and AIML Chat Bot

Install
--
If `pipenv` is not already installed:
`python3 -m pip install pipenv`


Clone repository to `/opt`
```
export PIPENV_VENV_IN_PROJECT=True && sudo -E pipenv install
sudo cp service_files/cassie.service /lib/systemd/system
sudo systemctl enable cassie.service
sudo cp config.yml.example config.yml
```
edit `config.yml` to fit your requirements
```
sudo systemctl start cassie.service
``` 

Required Packages
--
[Pipenv](https://github.com/pypa/pipenv)

[SleekXMPP](https://github.com/fritzy/SleekXMPP)

[PyAIML](https://github.com/zeroSteiner/pyAIML)

[Python-Markdown](http://pythonhosted.org/Markdown/)

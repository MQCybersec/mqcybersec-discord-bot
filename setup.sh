python3 -m venv .venv
. .venv/bin/activate
pip3 install -r requirements.txt
touch ctf_bot.db
cp .env.template ./.env
deactivate
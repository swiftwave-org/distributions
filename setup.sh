# !/bin/sh

if [ -z "$1" ]; then
    echo "Please provide a user name"
    exit 1
fi
if [ -z "$2" ]; then
    echo "Please provide a secret key"
    exit 1
fi

USER=$1
SECRET_KEY=$2
mkdir -p ./source
sudo rm -rf /var/www
sudo mkdir -p /var/www
sudo chmod  777 /var/www
sudo apt update -y
sudo apt install -y python3-pip nginx gcc dpkg-dev gpg rpm gnupg supervisor createrepo-c
pip install -r requirements.txt
sudo cp ./nginx.conf /etc/nginx/sites-available/default
sudo service nginx restart

BASE_PATH=$(pwd)
supervisor_cnf=$(cat "./supervisor.conf" | sed "s|USER|$USER|g")
supervisor_cnf=$(echo "$supervisor_cnf" | sed "s|BASE_PATH|$BASE_PATH|g")
supervisor_cnf=$(echo "$supervisor_cnf" | sed "s|SECRET_KEY_HERE|$SECRET_KEY|g")
sudo rm -f /etc/supervisor/conf.d/distributions.conf
echo "$supervisor_cnf" | sudo tee /etc/supervisor/conf.d/distributions.conf
sudo service supervisor restart
sudo supervisorctl restart all
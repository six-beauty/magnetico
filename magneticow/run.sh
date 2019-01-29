svr_port=5002
cur_dir=$(pwd)

run_status=$(/usr/sbin/lsof -nP -i TCP:$svr_port |grep python)

if [[ ${#run_status} > 0 ]];
then
    echo 'magneticow still running, '${#run_status}
    exit 0
else
    nohup python magn.py --cfg-file /home/hero/.local/share/magneticod/magn.cfg --no-auth --port $svr_port > /dev/null 2>&1 &
    echo 'magneticow stop('${#run_status}'), start work!'$(date +"%H:%M:%S")
fi


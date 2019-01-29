svr_port=6882
cur_dir=$(pwd)

#run_status=$(/usr/sbin/lsof -nP -i TCP:$svr_port |grep python)
run_status=$(ps aux |grep python |grep 6882)

if [[ ${#run_status} > 0 ]];
then
    echo 'magneticod still running, '${run_status#*python}
    exit 0
else
    nohup python 1.py --node-addr 0.0.0.0:$svr_port > /dev/null 2>&1 &
    echo 'magneticod stop('${run_status#*python}'), start work!'$(date +"%H:%M:%S")
fi


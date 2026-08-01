POD=`kubectl get pods -n quepid | grep quepid-api-unofficial | grep Running | head -1 | awk '{print $1}'`

kubectl exec -it $POD -n quepid --container api -- /bin/bash

#make sure host name at db_param.h file is mydb instead of localhost
FROM yunjingliu/world_sim:base
ADD . /worldsim
WORKDIR /worldsim
RUN chmod +x ./wait-for-it.sh ./server

#!/bin/bash
SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}"  )" &> /dev/null && pwd  )
DAEMON_NAME=${SCRIPT_DIR##*/}

# set permissions for script files
chmod a+x $SCRIPT_DIR/restart.sh
chmod 744 $SCRIPT_DIR/restart.sh

chmod a+x $SCRIPT_DIR/uninstall.sh
chmod 744 $SCRIPT_DIR/uninstall.sh

chmod a+x $SCRIPT_DIR/service/run
chmod 755 $SCRIPT_DIR/service/run

chmod a+x $SCRIPT_DIR/service/log/run
chmod 755 $SCRIPT_DIR/service/log/run

chmod a+x $SCRIPT_DIR/run.sh
chmod 755 $SCRIPT_DIR/run.sh

chmod a+x $SCRIPT_DIR/dbus-shelly-3em-smartmeter.py
chmod 755 $SCRIPT_DIR/dbus-shelly-3em-smartmeter.py



# create sym-link to run script in deamon
ln -s $SCRIPT_DIR/service /service/$DAEMON_NAME



# add install-script to rcS.local to be ready for firmware update
filename=/data/rcS.local
if [ ! -f $filename ]
then
    touch $filename
    chmod 755 $filename
    echo "#!/bin/bash" >> $filename
    echo >> $filename
fi

grep -qxF "$SCRIPT_DIR/install.sh" $filename || echo "$SCRIPT_DIR/install.sh" >> $filename

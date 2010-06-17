#!/bin/sh

TEDRX_DIR=~/
GRAPHS_DIR=~/teddata
WWW_DIR=/var/www

POWER_INTERVALS="8h 1h 1d 1w 1m"
URL_BASE="http://10.0.0.5"
RSSFILE="index.rss"

####### Restart Daemons

cd $TEDRX_DIR

(ps ax | grep ted-daemon | grep -v -q grep) || \
   nohup ./ted-daemon.py $GRAPHS_DIR > /dev/null 2> $GRAPHS_DIR/ted-daemon.log &

# ####### Update RSS file

date=`date`
hash=`date +%s`
cd $GRAPHS_DIR

# ( cat <<EOF
# EOF
# <?xml version="1.0" encoding="utf-8"?>
# <rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/">
# <channel>

# <title>Graphs</title>
# <ttl>2</ttl>
# EOF

### Power usage graphs

# for interval in $POWER_INTERVALS; do
#   url="$URL_BASE/kw-$interval.jpeg?t=$hash"

# cat <<EOF
#   <item>
#     <title>Power Usage ($interval)</title>
#     <link>$url</link>
#     <description>$url</description>
#     <pubDate>$date</pubDate>
#     <guid isPermaLink="false">kw-$interval-$hash</guid>
#     <media:content url="$url" type="image/jpeg" />
#   </item>
# EOF
# done

# echo "</channel></rss>" ) > $WWW_DIR/$RSSFILE.temp

# Atomically update the RSS file
#mv $WWW_DIR/$RSSFILE.temp $WWW_DIR/$RSSFILE

####### Power graphs

for interval in $POWER_INTERVALS; do

imgName=kw-$interval
graphTitle="Power Usage ($interval) - `date`"

if [ $interval = '1h' -o $interval = '8h' -o $interval = '1d' ]; then
    previous_interval='1d'
else 
    previous_interval=$interval
fi

echo "Interval $interval"
echo "Previous $previous_interval"

nice rrdtool graph $WWW_DIR/$imgName.png -a PNG -w 900 -h 455 \
--font DEFAULT:12:Vera.ttf \
-t "$graphTitle" \
--end now --start end-$interval \
    -v "Kilowatts" \
        DEF:kw=tedrx-kw.rrd:value:AVERAGE VDEF:vkw=kw,AVERAGE \
        DEF:kwmin=tedrx-kw.rrd:value:MIN \
        DEF:kwmax=tedrx-kw.rrd:value:MAX \
        DEF:kwlast=tedrx-kw.rrd:value:AVERAGE:end=now-1d:start=end-1d VDEF:vkwl=kwlast,AVERAGE \
        AREA:kwmax#cc8888 \
        AREA:kwmin#ffffff \
    LINE:kw#000000:"Current power usage" GPRINT:vkw:"%0.3lf kW\n"  \
    LINE:kwlast#0000ff:"Yesterday power usage" GPRINT:vkwl:"%0.3lf kW\n"  \

done

for interval in $POWER_INTERVALS; do

imgName=dollar-$interval
graphTitle="Dollar cost ($interval) - `date`"

nice rrdtool graph $WWW_DIR/$imgName.png -a PNG -w 900 -h 455 \
             --font DEFAULT:12:Vera.ttf \
             -u "1" -t "$graphTitle" \
             --end now --start end-$interval \
             -v "\$" \
                   DEF:d=tedrx-d.rrd:value:AVERAGE VDEF:vd=d,AVERAGE \
                   DEF:dmin=tedrx-d.rrd:value:MIN \
                   DEF:dmax=tedrx-d.rrd:value:MAX \
                   AREA:dmax#cc8888 \
                   AREA:dmin#ffffff \
             LINE:d#000000:"Current Cost" GPRINT:vd:"%0.3lf \$\n" \

done

bgperf
========

bgperf is a performance measurement tool for BGP implementation.

* [How to install](#how_to_install)
* [How to use](#how_to_use)
* [How bgperf works](https://github.com/osrg/bgperf/blob/master/docs/how_bgperf_works.md)
* [Benchmark remote target](https://github.com/osrg/bgperf/blob/master/docs/benchmark_remote_target.md)
* [MRT injection](https://github.com/osrg/bgperf/blob/master/docs/mrt.md)

## Updates
I've changed bgperf to work with python 3 and work with new versions of all the NOSes. It actually works, the original version that this is a from from does not work anymore because of newer version of python and each of the routing stacks.

 This version no longer compiles EXABGP or FRR, it gets PIP or containers already created. Quagga has been removed since it doesn't seem to be updated anymore.

To get bgperf to work with all the changes in each stack  I've had to change configuration. I 
don't know if all the features of bgperr still work: I've gotten the simplest version of
each config to work.

Caveats: 

I don't know if adding more policy will still work. 
I also don't know if I've configured each NOS for optimal performance.
I don't know if remote testing works.
I don't know if MRT works


## Prerequisites

* Python 3.7 or later
* Docker

##  <a name="how_to_install">How to install

```bash
$ git clone https://github.com:jopietsch/bgperf.git
$ cd bgperf
$ pip install -r pip-requirements.txt
$ ./bgperf.py --help
usage: bgperf.py [-h] [-b BENCH_NAME] [-d DIR]
                 {doctor,prepare,update,bench,config} ...

BGP performance measuring tool

positional arguments:
  {doctor,prepare,update,bench,config}
    doctor              check env
    prepare             prepare env
    update              pull bgp docker images
    bench               run benchmarks
    config              generate config

optional arguments:
  -h, --help            show this help message and exit
  -b BENCH_NAME, --bench-name BENCH_NAME
  -d DIR, --dir DIR
$ ./bgperf.py prepare
$ ./bgperf.py doctor
docker version ... ok (1.9.1)
bgperf image ... ok
gobgp image ... ok
bird image ... ok

## <a name="how_to_use">How to use

Use `bench` command to start benchmark test.
By default, `bgperf` benchmarks [GoBGP](https://github.com/osrg/gobgp).
`bgperf` boots 100 BGP test peers each advertises 100 routes to `GoBGP`.

```bash
$ sudo ./bgperf.py bench
run tester
tester booting.. (100/100)
run gobgp
elapsed: 16sec, cpu: 0.20%, mem: 580.90MB
elapsed time: 11sec
```

To change a target implementation, use `-t` option.
Currently, `bgperf` supports [BIRD](http://bird.network.cz/) and FRR
other than GoBGP.

```bash
$ sudo ./bgperf.py bench -t bird
run tester
tester booting.. (100/100)
run bird
elapsed: 16sec, cpu: 0.00%, mem: 147.55MB
elapsed time: 11sec
```

To change a load, use following options.

* `-n` : the number of BGP test peer (default 100)
* `-p` : the number of prefix each peer advertise (default 100)
* `-a` : the number of as-path filter (default 0)
* `-e` : the number of prefix-list filter (default 0)
* `-c` : the number of community-list filter (default 0)
* `-x` : the number of ext-community-list filter (default 0)

```bash
$ sudo ./bgperf.py bench -n 200 -p 50
run tester
tester booting.. (200/200)
run gobgp
elapsed: 23sec, cpu: 0.02%, mem: 1.26GB
elapsed time: 18sec
```

For a comprehensive list of options, run `sudo ./bgperf.py bench --help`.

## Debugging

If it doesn't seem to be working, try with 1 peer and 1 route (-n1 -p1) and make sure
that it connections. If it's just stuck at waiting to connect to the neighbor, then probably the config is wrong and neighbors are not being established between the monitor (gobgp) and the NOS being tested

You'll have to break into gobgp and the test config.


if you want to see what is happening when the test containers starts, after the test is over (or you've killed it), run 
```docker exec bgperf_bird_target /root/config/start.sh```
that's what bgperf is doing. It creates a /root/config/start.sh command and is running it, so if you run it manually you can see if that command produces output to help you debug.

to clean up any existing docker containers

```docker kill `docker ps -q` ```
```docker rm `docker ps -aq` ```
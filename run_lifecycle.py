#!/usr/bin/env python3
#
# Copyright (C) 2015, 2016 Nippon Telegraph and Telephone Corporation.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Run orchestration extracted from the CLI without changing its ordering.

The runtime argument is the calling engine module. Dependencies are read through
it at the same points as the original global lookups, including mutable stop
state, adapter registries and test substitutions. This module imports neither
the CLI nor Docker and starts no runtime on import. The broad compatibility
boundary is intentional for this mechanical extraction; narrowing it and
introducing lifecycle stages or new cleanup policy are separate changes.
"""

def bench(runtime, args):
    # Here as well as in `batch()`, because a single `bench` can be stopped
    # too. Idempotent: re-installing a handler replaces it with itself.
    runtime.install_stop_handlers()

    output_stats = {}
    config_dir = '{0}/{1}'.format(args.dir, args.bench_name)
    dckr_net_name = args.docker_network_name or args.bench_name + '-br'

    target_image_name = None
    # First, and outside the `-f` branch: the flag reaches nothing on either
    # path, and it reads only the command line.
    try:
        runtime.refuse_single_table(getattr(args, 'single_table', False),
                            '-s/--single-table')
    except ValueError as e:
        runtime.sys.exit(str(e))
    # Above the teardown, and before anything reads `prefix_num`: the row, the
    # artifact names and the scenario all take the per-peer count, so the
    # division happens once, here. A scope that cannot be applied should cost a
    # message rather than the previous run's containers -- which is why every
    # guard in this function sits above the teardown, and why the ones that
    # read only the command line sit above the one Docker call among them.
    # batch() has already divided by the time it gets here, which is why it
    # passes `per-peer` explicitly.
    if not args.file:
        # `check_batch_test()` refuses these on the batch path; nothing did
        # here. `resolve_prefix_scope()` is the single normalisation point but
        # it only rejects them under `total`, so `bench -n 0` reached
        # `gen_conf()` untouched, which builds a scenario with no testers and a
        # monitor check-point of `int(0 * 0.99)` -- satisfied at zero routes,
        # so the run writes a row that reads as a converged benchmark.
        for flag, value in (('-n/--neighbor-num', args.neighbor_num),
                            ('-p/--prefix-num', args.prefix_num)):
            if not runtime._is_positive_count(value):
                runtime.sys.exit('{0} must be a whole number of 1 or more, got '
                         '{1!r}'.format(flag, value))
        runtime.check_generator_matches_workload(args)
        try:
            args.receivers = runtime.resolve_receivers(getattr(args, 'receivers', None))
        except ValueError as e:
            runtime.sys.exit(str(e))
        # Before the scope, so a run asking for both is told they are not
        # defined together rather than being told the arithmetic of a
        # combination that is refused anyway.
        try:
            args.path_diversity = runtime.resolve_path_diversity(
                getattr(args, 'path_diversity', None), args.neighbor_num,
                getattr(args, 'tester_type', None),
                getattr(args, 'prefix_scope', None))
        except ValueError as e:
            runtime.sys.exit(str(e))
    if args.file and (getattr(args, 'receivers', None)
                      or runtime.DEFAULT_RECEIVERS) != runtime.DEFAULT_RECEIVERS:
        # A scenario file states every session the target has, receivers
        # included, so this would add nothing to the config and start
        # containers nobody peered with -- above the teardown, like the two
        # refusals beside it.
        runtime.sys.exit('--receivers has nothing to add under -f: a scenario file '
                 'states the sessions the target has itself')
    if getattr(args, 'pin', None) and args.repeat:
        # `--repeat` builds no tester objects: it reuses the tester containers
        # it finds, and a container's cpuset is fixed when it is created. The
        # generators would run on whatever cores the previous run gave them
        # while the stem and the manifest said otherwise.
        runtime.sys.exit('--pin cannot be honoured under -r/--repeat: the reused '
                 'tester containers keep the cores they were created with')
    churn_flags = runtime.churn_flags_set(getattr(args, 'churn_prefixes', None),
                                  getattr(args, 'churn_bursts', None))
    if args.file and churn_flags:
        # A scenario file states what each peer announces, and the churn block
        # is cut out of what bgperf2 generated -- there is nothing here to take
        # it from. Above the teardown like the refusals beside it. Both flags,
        # not just the block: `resolve_churn()` runs only for a generated
        # scenario, so `-f --churn-bursts 5` otherwise ran an ordinary run,
        # withdrew nothing and recorded `churn_bursts: null` in both manifests
        # -- the operator's flag gone without a word.
        runtime.sys.exit('{0} {1} nothing to withdraw under -f: a scenario file states '
                 "each neighbour's prefixes itself".format(
                     ' and '.join(churn_flags),
                     'have' if len(churn_flags) > 1 else 'has'))
    if args.file and (getattr(args, 'policy_reload_blocks', None)
                      or runtime.DEFAULT_POLICY_RELOAD_BLOCKS) \
            != runtime.DEFAULT_POLICY_RELOAD_BLOCKS:
        # A scenario file states the peers and the blocks they announce, and
        # the reload's policy is built from exactly those -- so there is
        # nothing here to select. Above the teardown, like the refusals beside
        # it, and refused rather than ignored for the reason the churn flags
        # are: accepted, the run would name its artifacts `pr<N>`, record the
        # workload in both manifests, and change no policy at all.
        runtime.sys.exit('--policy-reload-blocks has nothing to reject under -f: a '
                 "scenario file states each neighbour's prefixes itself")
    if args.file and (getattr(args, 'path_diversity', None)
                      or runtime.DEFAULT_PATH_DIVERSITY) != runtime.DEFAULT_PATH_DIVERSITY:
        # Same rule as the scope beside it, and above the teardown for the same
        # reason: a scenario file states each neighbour's paths, so grouping
        # them here would do nothing at all, and doing nothing quietly is worse
        # than the silence about `-n` and `-p` it joins.
        runtime.sys.exit('--path-diversity has nothing to group under -f: a scenario '
                 "file states each neighbour's paths itself")
    if args.file and getattr(args, 'prefix_scope', None) not in (None, 'per-peer'):
        # `-n`/`-p` are already ignored under `-f`, and this would be too --
        # but the whole point of the flag is that the number means something
        # different, so accepting it where it does nothing is worse than the
        # existing silence about the two it joins.
        runtime.sys.exit('--prefix-scope has nothing to divide under -f: a scenario '
                 'file states each neighbour\'s prefixes itself')
    if not args.file:
        try:
            args.prefix_num = runtime.resolve_prefix_scope(
                getattr(args, 'prefix_scope', None), args.neighbor_num,
                args.prefix_num, getattr(args, 'tester_type', None))
        except ValueError as e:
            runtime.sys.exit(str(e))
        # After the scope, because the block is taken out of each peer's own
        # list and `--prefix-scope total` is what decides how long that list
        # is: `-n 10 -p 1000 --prefix-scope total` gives every peer 100
        # prefixes, so a churn block of 500 is larger than what a peer
        # announces even though it is a fifth of the table.
        try:
            args.churn_prefixes, args.churn_bursts = runtime.resolve_churn(
                getattr(args, 'churn_prefixes', None),
                getattr(args, 'churn_bursts', None),
                args.neighbor_num, args.prefix_num,
                getattr(args, 'tester_type', None),
                getattr(args, 'filter_test', None))
        except ValueError as e:
            runtime.sys.exit(str(e))
        if args.churn_prefixes and args.repeat:
            # `-r/--repeat` reuses the tester *containers* and builds no tester
            # objects at all, so there is nothing to issue a burst through and
            # nothing rewrites the generator config the churn protocol lives
            # in. Accepted, the run would name its artifacts `ch<N>x<B>`,
            # record the workload in both manifests, and withdraw nothing --
            # the shape `--receivers` was found in one round earlier.
            runtime.sys.exit('--churn-prefixes cannot be used with -r/--repeat: '
                     'repeat reuses the generator containers as they are, so '
                     'the churn block is neither written into their config '
                     'nor reachable to withdraw')
        # After the scope for the reason churn is: the reload's block count is
        # checked against the peer count and the diversity, and `--prefix-scope
        # total` changes neither -- but the expected count it will be measured
        # against is `blocks x prefixes per peer`, so it must be the resolved
        # per-peer number. The churn values here are the normalised ones, which
        # is enough: `resolve_churn()` has already refused a bare
        # `--churn-bursts`, so anything still set is a real churn workload.
        try:
            args.policy_reload_blocks = runtime.resolve_policy_reload(
                getattr(args, 'policy_reload_blocks', None),
                args.neighbor_num,
                getattr(args, 'path_diversity', None),
                getattr(args, 'target', None),
                getattr(args, 'tester_type', None),
                getattr(args, 'filter_test', None),
                args.churn_prefixes, args.churn_bursts,
                getattr(args, 'repeat', False))
        except ValueError as e:
            runtime.sys.exit(str(e))

    if args.file:
        # A scenario's generators are otherwise only checked in the dispatch
        # loop, after the teardown below has already destroyed the previous
        # run's containers and logs.
        with open(args.file) as f:
            early = runtime.yaml.safe_load(runtime.Template(f.read()).render()) or {}
        try:
            for tester in early.get('testers') or []:
                if tester.get('type') == 'mrt':
                    runtime.scenario_mrt_tester_class(tester)
        except ValueError as e:
            runtime.sys.exit(str(e))

    if not args.file:
        # After every guard that reads only the command line, and still before
        # anything is torn down. Both halves matter: a typo'd --version must
        # cost nothing, since everything below destroys the previous run's
        # containers and config dir, which this repository keeps on purpose so
        # a failure can be investigated -- and this is a Docker call, so
        # running it *first* meant a mistyped -p or --path-diversity was
        # answered by `ImageNotBuilt` on a host with no daemon or no image, and
        # made the argument guards' own tests depend on which images happened
        # to be built. That suite deliberately needs no Docker.
        #
        # Only a -f scenario can declare the target remote, and a remote target
        # has no local image to resolve, so that case waits for the parse.
        #
        # The pin is resolved here, after every guard that reads only the
        # command line, because its last check reads the host's CPU list.
        try:
            args.pin = runtime.resolve_pin(getattr(args, 'pin', None), args.receivers,
                                   runtime.host_cpus())
        except ValueError as e:
            runtime.sys.exit(str(e))
        target_image_name = runtime.target_image(args.target,
                                         getattr(args, 'version', None),
                                         args.image)
    else:
        # A scenario file is checked before the teardown too, so a refusal
        # costs a message rather than the previous run's containers. The file
        # is read once, here, so the check and the run see the same text; it is
        # rendered again below rather than reused, because that render has
        # always sat inside `total time` and moving it out would shorten every
        # `-f` run's column relative to the rows it is compared with.
        with open(args.file) as f:
            scenario_text = f.read()
        try:
            early = runtime.render_scenario(scenario_text)
            runtime.refuse_scenario_single_table(
                early, "the scenario's target `single-table`")
            # Here rather than after the parse below, for the same reason
            # (bgperf2-urp): `resolve_receivers()` guards every path that
            # builds a scenario; this guards the one path handed one.
            runtime.scenario_receivers(early)
            if getattr(args, 'pin', None):
                # A remote target is not a container bgperf2 starts, so there
                # is nothing to give its cores to, and the scenario says how
                # many receivers the run has.
                if early.get('target', {}).get('remote'):
                    raise ValueError('--pin cannot be honoured for a remote '
                                     'target: bgperf2 does not start it')
                args.pin = runtime.resolve_pin(args.pin,
                                       len(early.get('receivers') or []),
                                       runtime.host_cpus())
        except ValueError as e:
            runtime.sys.exit(str(e))
        scenario_receiver_count = len(early.get('receivers') or [])
        del early
    # The instrument's image, on both paths -- a `-f` run starts the monitor
    # too -- and after every guard that reads only the command line, because
    # this asks Docker. Before the teardown, so a sink nobody built costs a
    # message rather than the previous run's containers; the GoBGP monitor was
    # never checked here, and a missing one failed at `create_container`.
    #
    # And the receivers' image, when the run has receivers: they are their own
    # class, and under `--monitor sink` that class was not the monitor's.
    receiver_count = (scenario_receiver_count if args.file
                      else getattr(args, 'receivers', None) or 0)
    try:
        runtime.MONITOR_CLASSES[runtime.run_monitor(args)].require_image()
        if receiver_count:
            runtime.RECEIVER_CLASSES[runtime.run_monitor(args)].require_image()
    except runtime.ImageNotBuilt as e:
        runtime.sys.exit(str(e))
    if args.repeat:
        # The other half of the `--pin` refusal under `--repeat`: an unpinned
        # run reusing generators a pinned run created would inherit their
        # cpuset, and be published as unpinned. A Docker call, so after every
        # guard that reads only the command line; before the teardown, so the
        # refusal costs nothing.
        pinned = runtime.pinned_tester_containers(
            runtime.get_ctn_names(),
            lambda name: runtime.dckr.inspect_container(name)['HostConfig'].get('CpusetCpus'))
        if pinned:
            runtime.sys.exit('-r/--repeat would reuse tester containers a pinned run '
                     'created ({0}), and they keep its cores. Run once without '
                     '-r to rebuild them'.format(', '.join(pinned)))
    runtime.remove_target_containers()

    if not args.repeat:
        runtime.remove_old_containers()

        if runtime.os.path.exists(config_dir):
            runtime.shutil.rmtree(config_dir, ignore_errors=True)

    # Only once the previous run's containers are gone. batch() reuses this
    # process for every cell, so checking earlier would see the last cell's own
    # target daemon still running and report it as somebody else's job.
    runtime.warn_if_machine_is_busy()
    runtime.warn_if_log_dir_is_in_ram(config_dir)
    runtime.warn_if_log_dir_is_short_on_space(config_dir)

    bench_start = runtime.time.time()
    if args.file:
        conf = runtime.render_scenario(scenario_text)
    else:
        conf = runtime.gen_conf(args)

        if not runtime.os.path.exists(config_dir):
            runtime.os.makedirs(config_dir)
        with open('{0}/scenario.yaml'.format(config_dir), 'w') as f:
            f.write(conf)
        conf = runtime.yaml.safe_load(runtime.Template(conf).render())

    # After the scenario is parsed, so this covers a -f run too -- which is one
    # of the ways the flag reaches nothing.
    runtime.warn_if_trace_io_reaches_no_generator(args, conf)

    # A `-f` run's fan-out is whatever the file says, so the notice waits for
    # the parse; the file's receivers were validated before the teardown.
    fanout_cost = runtime.describe_export_fanout_cost(len(conf.get('receivers') or []),
                                              runtime.run_monitor(args))
    if fanout_cost:
        print(fanout_cost)

    churn_prefixes = getattr(args, 'churn_prefixes', None) or runtime.DEFAULT_CHURN_PREFIXES
    churn_bursts = getattr(args, 'churn_bursts', None) or runtime.DEFAULT_CHURN_BURSTS
    churn_groups = None
    if churn_prefixes:
        # The block count the monitor's side of a burst is measured against,
        # from the one function that owns that arithmetic -- the same one
        # `gen_conf()` used for the check-point, so the two cannot disagree
        # about how many distinct prefixes a group's peers share.
        churn_groups = runtime.path_diversity_groups(
            args.neighbor_num,
            getattr(args, 'path_diversity', None) or runtime.DEFAULT_PATH_DIVERSITY)
        print(runtime.describe_churn_workload(churn_prefixes, churn_bursts,
                                      args.neighbor_num, churn_groups))

    policy_reload_blocks = (getattr(args, 'policy_reload_blocks', None)
                            or runtime.DEFAULT_POLICY_RELOAD_BLOCKS)
    if policy_reload_blocks:
        print(runtime.describe_policy_reload_workload(
            policy_reload_blocks, args.neighbor_num, args.prefix_num,
            getattr(args, 'path_diversity', None),
            getattr(runtime.TARGET_CLASSES.get(getattr(args, 'target', None)),
                    'POLICY_RELOAD_MECHANISM', None)))

    # A remote target is not a container bgperf2 starts, so it has no image --
    # resolving one would fail a remote run on the default target's image.
    is_remote = bool(conf['target'].get('remote'))
    if target_image_name is None and not is_remote:
        target_image_name = runtime.target_image(args.target, getattr(args, 'version', None), args.image)

    bridge_found = False
    for network in runtime.dckr.networks(names=[dckr_net_name]):
        if network['Name'] == dckr_net_name:
            print('Docker network "{}" already exists'.format(dckr_net_name))
            bridge_found = True
            break
    if not bridge_found:
        subnet = conf['local_prefix']
        print('creating Docker network "{}" with subnet {}'.format(dckr_net_name, subnet))
        ipam = runtime.IPAMConfig(pool_configs=[runtime.IPAMPool(subnet=subnet)])
        network = runtime.dckr.create_network(dckr_net_name, driver='bridge', ipam=ipam)

    # Every session the target holds, not just the route sources: this warns
    # about the kernel's ARP table, and a receiver occupies an entry in it
    # exactly as a generator peer does.
    num_tester = (sum(len(t.get('neighbors', [])) for t in conf.get('testers', []))
                  + len(conf.get('receivers') or []))
    if num_tester > runtime.gc_thresh3():
        print('gc_thresh3({0}) is lower than the number of peer({1})'.format(runtime.gc_thresh3(), num_tester))
        print('type next to increase the value')
        print('$ echo 16384 | sudo tee /proc/sys/net/ipv4/neigh/default/gc_thresh3')

    # Every role this run has was checked to be named, disjoint and on this
    # host before anything was torn down; {} on an unpinned run.
    pin = runtime.pin_cpusets(getattr(args, 'pin', None))

    print('run monitor')
    m = runtime.MONITOR_CLASSES[runtime.run_monitor(args)](config_dir+'/monitor', conf['monitor'])
    m.monitor_for = args.target
    m.cpuset = pin.get('monitor')
    m.run(conf, dckr_net_name)

    # Started with the monitor and established before any generator launches:
    # a receiver that came up mid-run would take a partial table and the export
    # work would land on the target at a moment nothing recorded, which is the
    # one thing this fan-out exists to measure.
    #
    # Built on every run, `-r/--repeat` included, because that is the monitor's
    # contract and a receiver is a monitor in every respect but being read.
    # `--repeat` reuses the *tester* containers; `Container.run()` removes and
    # recreates anything else it finds by name, and the target is rebuilt from
    # scratch under it too, so every receiver session has to be re-established
    # anyway. Skipping them under `--repeat` meant the count the target was
    # configured for, the count in the artifact name and the count in the
    # manifest were three claims about sessions that did not exist.
    receivers_wanted = conf.get('receivers') or []
    for name in runtime.surplus_receiver_names(runtime.get_ctn_names(), len(receivers_wanted)):
        # The one case recreating by name does not cover: a run asking for
        # fewer than the last built leaves the rest up, and under `--repeat`
        # nothing else removes them.
        print('removing surplus receiver container', name)
        runtime.dckr.remove_container(name, force=True)
    receiver_containers = []
    for idx, receiver in enumerate(receivers_wanted):
        r = runtime.RECEIVER_CLASSES[runtime.run_monitor(args)](
            idx, '{0}/receiver{1}'.format(config_dir, idx), receiver)
        r.cpuset = pin.get('receivers')
        print('run receiver', r.name)
        r.run(conf, dckr_net_name)
        receiver_containers.append(r)


    ## I'd prefer to start up the testers and then start up the target
    # however, bgpdump2 isn't smart enough to wait and rety connections so
    # this is the order
    testers = []
    mrt_injector = None
    if not args.repeat:
        valid_indexes = None
        asns = None
        for idx, tester in enumerate(conf['testers']):
            if 'name' not in tester:
                name = 'tester{0}'.format(idx)
            else:
                name = tester['name']
            if not 'type' in tester:
                tester_type = 'bird'
            else:
                tester_type = tester['type']
            if tester_type == 'exa':
                tester_class = runtime.ExaBGPTester
            elif tester_type == 'bird':
                tester_class = runtime.BIRDTester
            elif tester_type == 'mrt':
                mrt_injector = tester.get('mrt_injector')
                try:
                    tester_class = runtime.scenario_mrt_tester_class(tester)
                except ValueError as e:
                    runtime.sys.exit(str(e))

            else:
                print('invalid tester type:', tester_type)
                runtime.sys.exit(1)


            t = tester_class(name, config_dir+'/'+name, tester)
            t.cpuset = pin.get('testers')
            if not mrt_injector:
                print('run tester', name, 'type', tester_type)
            else:
                print('run tester', name, 'type', tester_type, mrt_injector)
            if idx > 0:
                runtime.rm_line()
            t.run(conf['target'], dckr_net_name)
            testers.append(t)


            # have to do some extra stuff with bgpdump2
            #  because it's sending real data, we need to figure out
            #  wich neighbor has data and what the actual ASN is
            if tester_type == 'mrt' and mrt_injector == 'bgpdump2' and not valid_indexes:
                print("finding asns and such from mrt file")
                valid_indexes = t.get_index_valid(args.prefix_num)
                asns = t.get_index_asns()

                for test in conf['testers']:
                    test['bgpdump-index'] = valid_indexes[test['mrt-index'] % len(valid_indexes)]
                    neighbor = next(iter(test['neighbors'].values()))
                    neighbor['as'] = asns[test['bgpdump-index']]

                # TODO: this needs to all be moved to it's own object and file
                #  so this stuff isn't copied around
                str_conf = runtime.gen_mako_macro() + runtime.yaml.dump(conf, default_flow_style=False)
                with open('{0}/scenario.yaml'.format(config_dir), 'w') as f:
                    f.write(str_conf)

    # Bound before the branch, because only one of the two branches binds it.
    # A remote run has no target container at all, and `abandon_run()` reads
    # this to stop the target's sampler: unbound, a stop on a remote run dies
    # with a `NameError` *before* the samplers are stopped, which is the one
    # thing abandoning a run may not skip.
    target = None
    if is_remote:
        print('target is remote ({})'.format(conf['target']['local-address']))

        ip = runtime.IPRoute()

        # r: route to the target
        r = ip.get_routes(dst=conf['target']['local-address'], family=runtime.AF_INET)
        if len(r) == 0:
            print('no route to remote target {0}'.format(conf['target']['local-address']))
            runtime.sys.exit(1)

        # intf: interface used to reach the target
        idx = [t[1] for t in r[0]['attrs'] if t[0] == 'RTA_OIF'][0]
        intf = ip.get_links(idx)[0]
        intf_name = intf.get_attr('IFLA_IFNAME')

        # raw_bridge_name: Linux bridge name of the Docker bridge
        # TODO: not sure if the linux bridge name is always given by
        #       "br-<first 12 characters of Docker network ID>".
        raw_bridge_name = args.bridge_name or 'br-{}'.format(network['Id'][0:12])

        # raw_bridges: list of Linux bridges that match raw_bridge_name
        raw_bridges = ip.link_lookup(ifname=raw_bridge_name)
        if len(raw_bridges) == 0:
            if not args.bridge_name:
                print(('can\'t determine the Linux bridge interface name starting '
                      'from the Docker network {}'.format(dckr_net_name)))
            else:
                print(('the Linux bridge name provided ({}) seems nonexistent'.format(
                      raw_bridge_name)))
            print(('Since the target is remote, the host interface used to '
                    'reach the target ({}) must be part of the Linux bridge '
                    'used by the Docker network {}, but without the correct Linux '
                    'bridge name it\'s impossible to verify if that\'s true'.format(
                        intf_name, dckr_net_name)))
            if not args.bridge_name:
                print(('Please supply the Linux bridge name corresponding to the '
                      'Docker network {} using the --bridge-name argument.'.format(
                          dckr_net_name)))
            runtime.sys.exit(1)

        # intf_bridge: bridge interface that intf is already member of
        intf_bridge = intf.get_attr('IFLA_MASTER')

        # if intf is not member of the bridge, add it
        if intf_bridge not in raw_bridges:
            if intf_bridge is None:
                print(('Since the target is remote, the host interface used to '
                      'reach the target ({}) must be part of the Linux bridge '
                      'used by the Docker network {}'.format(
                          intf_name, dckr_net_name)))
                runtime.sys.stdout.write('Do you confirm to add the interface {} '
                                 'to the bridge {}? [yes/NO] '.format(
                                     intf_name, raw_bridge_name
                                    ))
                try:
                    answer = input()
                except:
                    print('aborting')
                    runtime.sys.exit(1)
                answer = answer.strip()
                if answer.lower() != 'yes':
                    print('aborting')
                    runtime.sys.exit(1)

                print('adding interface {} to the bridge {}'.format(
                    intf_name, raw_bridge_name
                ))
                br = raw_bridges[0]

                try:
                    ip.link('set', index=idx, master=br)
                except Exception as e:
                    print(('Something went wrong: {}'.format(str(e))))
                    print(('Please consider running the following command to '
                          'add the {iface} interface to the {br} bridge:\n'
                          '   sudo brctl addif {br} {iface}'.format(
                              iface=intf_name, br=raw_bridge_name)))
                    print('\n\n\n')
                    raise
            else:
                curr_bridge_name = ip.get_links(intf_bridge)[0].get_attr('IFLA_IFNAME')
                print(('the interface used to reach the target ({}) '
                      'is already member of the bridge {}, which is not '
                      'the one used in this configuration'.format(
                          intf_name, curr_bridge_name)))
                print(('Please consider running the following command to '
                        'remove the {iface} interface from the {br} bridge:\n'
                        '   sudo brctl addif {br} {iface}'.format(
                            iface=intf_name, br=curr_bridge_name)))
                runtime.sys.exit(1)
    else:
        target_class = runtime.TARGET_CLASSES[args.target]
        print('run', runtime.run_name(args))
        target = target_class('{0}/{1}'.format(config_dir, args.target), conf['target'],
                              image=target_image_name)
        target.cpuset = pin.get('target')

        target.run(conf, dckr_net_name)

    runtime.time.sleep(1)

    output_stats['monitor_wait_time'] = m.wait_established(conf['target']['local-address'])
    # Not folded into `monitor_wait_time`: that column is the instrument coming
    # up, and adding the fan-out's establishment to it would make a
    # `--receivers 20` run look like a slow monitor in every published row.
    for r in receiver_containers:
        r.wait_established(conf['target']['local-address'], role=r.name)
    output_stats['cores'], output_stats['memory'] = runtime.get_hardware_info()
    # target_class is only bound in the local branch above; a remote run used to
    # die here with NameError. Pre-existing, but the remote path is now something
    # bench() explicitly supports resolving for.
    if not is_remote and target_class == runtime.EosTarget:
        print("Waiting extra 10 seconds for EOS ")
        runtime.time.sleep(10)

    # Resolved before the clock starts; see role_cpu_members().
    role_cpu_roles, role_cpu_unmeasured = runtime.role_cpu_members(
        None if is_remote else target, m, testers, receiver_containers,
        repeat=args.repeat)

    bench_clock_started_s = runtime.time.monotonic()
    lifecycle = runtime.MonitorEventRecorder(
        bench_clock_started_s, producer=m.name,
        sample_interval_s=runtime.MONITOR_POLL_INTERVAL_S)

    q = runtime.Queue()

    # Let the previous run's samplers go before starting this run's. batch()
    # reuses this process for every cell, so without the clear the new threads
    # would exit immediately on a flag the last run left set.
    runtime.controller_stop.clear()

    m.stats(q, interval=runtime.MONITOR_POLL_INTERVAL_S)
    runtime.controller_idle_percent(q)
    runtime.controller_memory_free(q)
    runtime.controller_foreign_cpu(q)
    role_cpu = runtime.RoleCpuRecorder(bench_clock_started_s, role_cpu_roles,
                               role_cpu_unmeasured)
    role_cpu_thread = runtime.controller_role_cpu(role_cpu, runtime.controller_stop)
    if not is_remote:
        target.stats(q)
        target.neighbor_stats(q)

    # The export side of the run. Without it a `--receivers 20` run and a
    # `--receivers 0` run differ in exactly one published number -- `elapsed
    # (s)` -- and what the fan-out cost the target is inside it, indivisible
    # from a slow daemon. The receivers were established before the clock
    # started, so a count of 0 on the first round is a session waiting for the
    # target rather than one still coming up.
    export_lifecycle = None
    export_state = {}
    export_read_failures = {}
    export_unmeasured = None
    # Per run and never cleared, unlike `controller_stop`: it closes the
    # delivery window this measurement covers, and it is what keeps a round
    # still in flight at the end of a batch cell from finding the controller's
    # own event clear again at the start of the next one.
    export_stop = runtime.threading.Event()
    export_thread = None
    export_required = int(conf['monitor']['check-points'][0])
    # A second workload run against the converged table and the receiver poll
    # cannot both be measured in one run, and this is where that was settled
    # after eight rounds of review kept finding the same seam from new sides.
    # The poll's window closes at convergence, which is exactly where churn and
    # the reload begin, so every way of making them coexist costs something
    # published: letting the poll run on puts N `docker exec`s inside a burst's
    # 1.0s-resolution withdrawal and the reload's CPU interval; waiting for it
    # instead puts that wait inside `total time` -- a graphed column, moving
    # with the *instrument's* fan-out -- and leaves the workload's recorder
    # dating its first sample across the wait, so a withdrawal resolved to a
    # second is published as "within the 25.0s poll resolution".
    #
    # So the run keeps the fan-out and declines to measure it, on the rule this
    # phase has already applied twice: `--prefix-scope total` under
    # `--path-diversity`, and churn beside a policy reload. Measuring export
    # and a post-convergence workload in one run means fixing an order and
    # paying for it somewhere published, and choosing that is its own change
    # set. The receivers still exist, still hold the table and still cost the
    # target its export work -- only the timing of it is withheld, by name.
    export_second_workload = bool(churn_prefixes or policy_reload_blocks)
    if receiver_containers and export_required > 0 \
            and not export_second_workload:
        export_lifecycle = runtime.ExportEventRecorder(
            bench_clock_started_s,
            [r.name for r in receiver_containers],
            export_required,
            sample_interval_s=runtime.RECEIVER_POLL_INTERVAL_S)
        export_thread = runtime.controller_export_stats(
            receiver_containers, export_lifecycle, export_state,
            export_read_failures, runtime.controller_stop, runtime.RECEIVER_POLL_INTERVAL_S,
            delivery_stop=export_stop)
    elif receiver_containers and export_second_workload:
        export_unmeasured = (
            'this run also drives a post-convergence workload, whose intervals '
            'are measured off the same target across the same boundary; '
            'measuring both in one run is deferred')
        print('export fan-out: not measured -- {0}'.format(export_unmeasured))
    elif receiver_containers:
        # `gen_conf()` takes 99% of the table, so `-p 1` -- the fastest
        # end-to-end check there is -- gives a check-point of 0, and a
        # threshold of 0 would stamp every receiver complete on the first round
        # and publish a table nobody was seen holding. Refused here rather than
        # inside the recorder, which would raise with the containers already
        # up: an instrument that cannot measure must cost the measurement, not
        # the run.
        #
        # This is the only *knowable* way the yardstick can be unusable. A
        # `--filter_test` policy can also put the check-point out of reach, by
        # dropping enough of the table that nothing re-advertises it -- but
        # whether it does depends on the policy and the workload, not on the
        # flag: `--filter_test transit` at 2 peers x 1000 prefixes converged at
        # the check-point on this host, so refusing here on the flag would
        # withhold a measurement that can be made. That case is reported from
        # the evidence instead -- see `describe_export_metrics()`, which reads
        # whether the *monitor* reached the count before blaming a receiver for
        # not reaching it.
        export_unmeasured = (
            'the run\'s monitor check-point is {0}, so no receiver can be '
            'observed holding the table'.format(export_required))
        print('export fan-out: not measured -- {0}'.format(export_unmeasured))


    # want to launch all the neighbors at the same(ish) time
    # launch them after the test starts because as soon as they start they can send info at least for mrt
    #  does it need to be in a different place for mrt than exabgp?
    for i in range(len(testers)):
        testers[i].launch()
        if i > 0:
            runtime.rm_line()
        print(f"launched {i+1} testers")
        # if args.prefix_num >= 100_000:
        #     time.sleep(1)

    # Ask the generators themselves what they have put on the wire. This is
    # measured at the tester, so an injection interval is evidence rather than
    # something inferred from when the monitor happened to see prefixes -- the
    # legacy `testers (s)` column is that inference, and it cannot tell a slow
    # generator from a slow target. Polling starts after launch because nothing
    # is running in those containers until start.sh has been exec'd.
    tester_lifecycles = {}
    tester_observation_errors = {}
    tester_read_failures = {}
    for t in testers:
        if not getattr(t, 'REPORTS_OFFERING', False):
            continue
        tester_lifecycles[t.name] = runtime.TesterEventRecorder(
            bench_clock_started_s, producer=t.name,
            sample_interval_s=runtime.TESTER_POLL_INTERVAL_S)
        t.offering_stats(q, runtime.controller_stop, runtime.TESTER_POLL_INTERVAL_S)

    f = open(args.output, 'w') if args.output else None
    cpu = 0
    mem = 0

    output_stats['max_cpu'] = 0
    output_stats['max_mem'] = 0
    output_stats['first_received_time'] = runtime.datetime.timedelta(0)
    output_stats['min_idle'] = 100
    output_stats['min_free'] = runtime.UNSAMPLED_MIN_FREE
    output_stats['max_foreign_cpu'] = 0
    # None until a sample sets the maximum: a run that never sampled and a run
    # whose competitors could not be named must not both read as a run that
    # looked and found nobody.
    output_stats['max_foreign_cpu_processes'] = None
    # finish_bench() fills these in once the clock has stopped; a run with no
    # testers (a remote target) never gets there, and they are printed and
    # written into the row unconditionally.
    output_stats['tester_errors'] = 0
    output_stats['tester_timeouts'] = 0

    output_stats['required'] = conf['monitor']['check-points'][0]
    bench_stats = []
    neighbors_checked = 0
    neighbors_received_full = 0
    percent_idle = 0
    mem_free = 0

    recved = 0
    # The target's own account of the table it holds, refreshed by its
    # neighbour poll and read on every monitor sample. The monitor is one BGP
    # session's view of the target and it is the only instrument every
    # published timing comes from, so a move in its count has nothing to be
    # checked against; this is the second witness. Empty for a daemon that has
    # no gauge to read, and that emptiness is what keeps such a run's artifact
    # exactly the shape it has always had.
    latest_witness = None
    latest_witness_s = None
    target_table_samples = []
    # The windows are durations; the tracker counts them in samples at the
    # cadence the monitor is asked for (measurement plan 7b).
    tracker = runtime.ConvergenceTracker(sample_interval_s=runtime.MONITOR_POLL_INTERVAL_S)
    while True:
        # Checked once per queue message, which is at least once a second: a
        # cell that would otherwise run for tens of minutes past a SIGTERM
        # gives the time back instead.
        if runtime.stop_signal.is_set():
            runtime.abandon_run(runtime.stop_signal.reason, target, m, testers)
        info = q.get()

        if not is_remote and info['who'] == target.name:
            if 'neighbors_checked' in info:
                # Rides on this message so the dispatch below keeps reading
                # anything with neither neighbour key as a cpu/mem sample.
                if 'table_witness' in info:
                    latest_witness = info['table_witness']
                    latest_witness_s = info.get('monotonic_s')
                if len(info['neighbors_checked']) > 0 and all(value == True for value in info['neighbors_checked'].values()):
                    neighbors_checked = sum(1 if value == True else 0 for value in info['neighbors_checked'].values())
                    tracker.note_neighbors_checkpoint()
                else:
                    neighbors_checked = sum(1 if value == True else 0 for value in info['neighbors_checked'].values())
            elif 'neighbors_received_full' in info:

                if len(info['neighbors_received_full']) >= 1 and all(value == True for value in info['neighbors_received_full'].values()):
                    neighbors_received_full = sum(1 if value == True else 0 for value in info['neighbors_received_full'].values())
                    tracker.note_neighbors_checkpoint()
                else:
                    neighbors_received_full = sum(1 if value == True else 0 for value in info['neighbors_received_full'].values())
            else:
                cpu = info['cpu']
                mem = info['mem']
                output_stats['max_cpu'] = cpu if cpu > output_stats['max_cpu'] else output_stats['max_cpu']
                output_stats['max_mem'] = mem if mem > output_stats['max_mem'] else output_stats['max_mem']

        if info['who'] == 'controller':
            if 'free' in info:
                mem_free = info['free']
                output_stats['min_free'] = mem_free if mem_free < output_stats['min_free'] else output_stats['min_free']
            elif 'idle' in info:
                percent_idle = info['idle']
                output_stats['min_idle'] = percent_idle if percent_idle < output_stats['min_idle'] else output_stats['min_idle']
            elif 'foreign_cpu' in info:
                runtime.note_foreign_cpu_sample(output_stats, info)
        if 'tester_offering' in info:
            runtime.observe_tester_sample(info, tester_lifecycles,
                                  tester_observation_errors)
        elif 'tester_offering_error' in info:
            runtime.note_tester_read_failure(info, tester_read_failures)

        if info['who'] == m.name:

            sample_monotonic_s = runtime.monitor_sample_monotonic_s(info)
            elapsed = runtime.datetime.timedelta(
                seconds=sample_monotonic_s - bench_clock_started_s)
            output_stats['elapsed'] = elapsed
            recved = info['afi_safis'][0]['state']['accepted'] if 'accepted' in info['afi_safis'][0]['state'] else 0
            # `monitor_required_reached` is the monitor's count against
            # `conf['monitor']['check-points'][0]`, and stays that and only
            # that. A second rule keyed on the target's own export count was
            # built here and backed out: see the plan's Block 5 record. It
            # could be made to fire mid-delivery -- the neighbour checkpoint
            # can be set while export is still in progress, and one poll in
            # which the target's export count does not advance with the
            # monitor drained to that same number stamps the event at a
            # fraction of the table. The event is recorded once, so that
            # mis-dates `convergence_s`, `assurance_s` and
            # `post_injection_tail_s` permanently and silently. A wrong
            # headline timing is worse than a missing one, which is why an
            # MRT run on a daemon that never reaches the check-point still
            # publishes none of the three rather than three plausible numbers.
            #
            # Under `--monitor sink` the three monitor events are dated to the
            # sink's own log lines rather than to this poll (measurement plan
            # 7b). The poll still decides *that* each happened, so nothing the
            # tracker or the row reads from the sample moves; only the
            # events' timestamps and resolutions sharpen.
            lifecycle.observe(sample_monotonic_s, int(recved),
                              info['checked'],
                              sink=runtime.sink_event_dates(
                                  info.get('sink'),
                                  runtime.SINK_CLOCK_OFFSET_LIMIT_NS))
            measured = runtime.monitor_metrics(lifecycle.events)
            if measured['first_prefix_s'] is not None:
                output_stats['first_received_time'] = runtime.datetime.timedelta(
                    seconds=measured['first_prefix_s'])

            # The target's own reading of the table it holds goes in beside
            # the monitor's count, so a decline in what one session is served
            # can be told from a decline in what the target has. Absent for a
            # daemon with no gauge, which is every daemon but BIRD, and such a
            # run is decided exactly as it always was.
            excused_before = tracker.witness_excused_samples
            status = tracker.update(elapsed.seconds, recved, neighbors_checked,
                                    neighbors_received_full, info['checked'],
                                    table_witness=latest_witness,
                                    witness_monotonic_s=latest_witness_s,
                                    offering_complete=runtime.tester_offering_complete(
                                        tester_lifecycles,
                                        tester_observation_errors))

            if elapsed.seconds > 0:
                runtime.rm_line()

            if latest_witness:
                # Paired with this monitor sample rather than carried on a
                # clock of its own: the whole point is the comparison, and the
                # witness's own timestamp is kept beside it so a reader can see
                # how stale the pairing is.
                target_table_samples.append({
                    'monotonic_s': round(
                        sample_monotonic_s - bench_clock_started_s, 6),
                    'witness_monotonic_s': (
                        None if latest_witness_s is None else
                        round(latest_witness_s - bench_clock_started_s, 6)),
                    # How old the carried reading was when this monitor sample
                    # took it. The target's poll is a separate thread with no
                    # guard around its exec, so if it stops, every later sample
                    # repeats the same reading and the series would report a
                    # perfectly stable table for a target nobody was asking.
                    # Signed and unclamped, on `post_injection_tail_s`'s rule:
                    # the two loops are independent, so a target read taken
                    # just after a monitor sample is ordinary and reads
                    # negative. Bounded by one poll either way, and staleness
                    # is the positive side.
                    'witness_age_s': (
                        None if latest_witness_s is None else
                        round(sample_monotonic_s - latest_witness_s, 6)),
                    'monitor_accepted': int(recved),
                    'best_paths': latest_witness.get('best_paths'),
                    'imported_paths': latest_witness.get('imported_paths'),
                    'exported_to_monitor': latest_witness.get(
                        'exported_to_monitor'),
                    'peerings': latest_witness.get('peerings'),
                    'peerings_expected': latest_witness.get(
                        'peerings_expected'),
                    'peerings_measured': latest_witness.get(
                        'peerings_measured'),
                })

            print('elapsed: {0}sec, cpu: {1:>4.2f}%, mem: {2}, mon recved: {3}, neighbors_received: {4}, neighbors_accepted: {5}, %idle {6}, free mem {7}'.format(elapsed.seconds,
                    cpu, runtime.mem_human(mem), recved, neighbors_received_full, neighbors_checked, percent_idle, runtime.mem_human(mem_free))
                  # Appended only for a target that can be asked *and*
                  # answered: the witness dict is truthy even when the sums
                  # were withheld, and every BIRD run withholds them during
                  # session ramp-up, so printing unconditionally puts
                  # `target holds: None prefixes` into the stdout log that the
                  # decision log cites as evidence. Tested against None rather
                  # than truthiness: a target with every session up and no
                  # routes yet has legitimately measured 0, and collapsing that
                  # into the withheld case hides the one this guard is for.
                  #
                  # Each half stands on its own, because the two daemons that
                  # answer answer differently: FRR publishes `imported_paths`
                  # and `exported_to_monitor` and withholds `best_paths` by
                  # design, so gating the whole suffix on `best_paths` printed
                  # nothing target-side for an FRR run while sampling both of
                  # the numbers it does have once a second -- leaving an
                  # operator watching a full-table cell unable to tell a
                  # stalled export from an ongoing import.
                  + runtime.target_holds_suffix(latest_witness))
            if tracker.witness_excused_samples > excused_before \
                    and excused_before == 0:
                # Once, on the first sample the witness saved, and never again:
                # a 1.5%-below-peak MRT table stays there for the rest of the
                # run, so one line per sample would be forty copies of the same
                # sentence in the log this decision is read from. What it
                # excused in total is in the artifact.
                print('the monitor is {0:.2f}% below its peak of {1} while the '
                      'target holds {2} prefixes, {3:.2f}% below its own peak: '
                      'reading the decline as export change, not route '
                      'loss'.format(
                          100.0 * tracker.max_excused_decline,
                          tracker.peak_recved,
                          (latest_witness or {}).get('best_paths'),
                          100.0 * tracker.max_excused_witness_decline))
            bench_stats.append([elapsed.seconds, float(f"{cpu:>4.2f}"), mem, recved, neighbors_checked, percent_idle, mem_free])
            f.write('{0}, {1}, {2}, {3}\n'.format(elapsed.seconds, cpu, mem, recved)) if f else None
            f.flush() if f else None

            if status == runtime.ConvergenceTracker.FAILED:
                # Close the export window here as well as on the converged
                # path: what a failed run's receivers had been served is worth
                # publishing, and the poll must not outlive the loop that
                # feeds its samples to the recorder.
                export_stop.set()
                output_stats['recved'] = recved
                output_stats['fail_msg'] = tracker.fail_msg
                f.close() if f else None
                print("FAILED")
                return runtime.finish_bench(
                    args, output_stats, bench_stats, bench_start, target, m,
                    testers, fail=True, lifecycle_events=lifecycle.events,
                    tester_lifecycles=tester_lifecycles,
                    tester_observation_errors=tester_observation_errors,
                    tester_read_failures=tester_read_failures,
                    export_lifecycle=export_lifecycle,
                    export_state=export_state,
                    export_read_failures=export_read_failures,
                    export_required=export_required,
                    export_receiver_names=[r.name for r in receiver_containers],
                    export_unmeasured_reason=export_unmeasured,
                    export_thread=export_thread,
                    role_cpu=(role_cpu, role_cpu_thread),
                    target_table=target_table_samples,
                    target_table_unmeasured_reason=runtime.target_table_unmeasured(
                        target, target_table_samples),
                    target_table_witness_rule=tracker.witness_rule(),
                    convergence_rule=tracker.convergence_rule())

            if status == runtime.ConvergenceTracker.CONVERGED:
                # Before the post-convergence workloads, which take this queue
                # over and skip anything that is not a monitor sample: a round
                # landing during a churn burst or a reload would be dropped,
                # and a receiver crossing the check-point in it would be
                # published as one that was never served. The export
                # measurement covers the delivery of the table, which is what
                # this sample has just settled.
                export_stop.set()
                if churn_prefixes or policy_reload_blocks:
                    # Whatever is in the queue at this point is stale, and the
                    # workload about to start dates its own beginning from the
                    # first sample it takes -- so a backlog makes the first
                    # burst look as though it began before the `birdc` that
                    # carried it, against a published 1.0s resolution. The main
                    # loop keeps this queue nearly empty, so the backlog is a
                    # message or two; that is still up to a whole poll of
                    # mis-dating on the one measurement whose resolution is a
                    # single poll.
                    runtime.drain_stale_samples(q)
                lifecycle.confirm_convergence(sample_monotonic_s)
                assurance = tracker.assurance_samples
                output_stats['recved'] = recved

                f.close() if f else None

                # Drop the trailing assurance samples: the run was already done
                # by then, we were only confirming the count had stopped moving.
                # TODO: recalculate all min/max stats after removing these
                #  should move to always calculating based on bench_stats
                print(f"last recevied: {tracker.last_recved_count}")
                # The window is `assurance` samples, so it is that many polls
                # of time -- not that many seconds, which it only was at 1 s.
                output_stats['elapsed'] = runtime.datetime.timedelta(
                    seconds=int(output_stats['elapsed'].seconds)
                    - round((assurance - 1) * runtime.MONITOR_POLL_INTERVAL_S))
                bench_stats = bench_stats[0:len(bench_stats)-assurance]
                # The second workload, run against the table this run has just
                # been measured delivering. It is after every column of the row
                # has been settled on purpose: `elapsed (s)` is the delivery,
                # and a burst's cost belongs in the artifact where it can be
                # read per burst rather than folded into a peak.
                churn_events, churn_evidence = runtime.churn_phase(
                    args, q, m, testers, sample_monotonic_s, int(recved),
                    churn_prefixes, churn_bursts, churn_groups)
                # The third workload, and refused alongside churn at every
                # entry point -- so at most one of these two ever runs against
                # a given converged table and neither takes the other's outcome
                # as its baseline.
                reload_events, reload_evidence = runtime.policy_reload_phase(
                    args, q, m, target, sample_monotonic_s, int(recved),
                    policy_reload_blocks, conf)
                if reload_evidence and not reload_evidence['reload_complete']:
                    # Into MSG without marking the row FAILED, exactly as an
                    # incomplete churn sequence is: the run converged and that
                    # measurement stands, and a batch of reload cells whose
                    # rows all read as ordinary would say nothing about the
                    # second workload.
                    output_stats['fail_msg'] = reload_evidence[
                        'incomplete_reason'] or 'the policy reload did not complete'
                if churn_evidence and not churn_evidence['sequence_complete']:
                    # Into the row's MSG column without setting its FAILED
                    # flag. The run converged and that measurement stands; what
                    # did not happen is the churn, and a CSV that said nothing
                    # about it would be a batch of churn cells whose rows all
                    # look ordinary. `summary.py` reads MSG only for a row
                    # marked failed, so no summary is affected.
                    output_stats['fail_msg'] = churn_evidence[
                        'incomplete_reason'] or 'churn did not complete'
                return runtime.finish_bench(
                    args, output_stats, bench_stats, bench_start, target, m,
                    testers,
                    lifecycle_events=(list(lifecycle.events)
                                      + list(churn_events)
                                      + list(reload_events)),
                    tester_lifecycles=tester_lifecycles,
                    tester_observation_errors=tester_observation_errors,
                    tester_read_failures=tester_read_failures,
                    export_lifecycle=export_lifecycle,
                    export_state=export_state,
                    export_read_failures=export_read_failures,
                    export_required=export_required,
                    export_receiver_names=[r.name for r in receiver_containers],
                    export_unmeasured_reason=export_unmeasured,
                    export_thread=export_thread,
                    role_cpu=(role_cpu, role_cpu_thread),
                    churn_evidence=churn_evidence,
                    policy_reload_evidence=reload_evidence,
                    target_table=target_table_samples,
                    target_table_unmeasured_reason=runtime.target_table_unmeasured(
                        target, target_table_samples),
                    target_table_witness_rule=tracker.witness_rule(),
                    convergence_rule=tracker.convergence_rule())

            if elapsed.seconds % 120 == 0 and elapsed.seconds > 1:
                # The same stem the final graphs use. Built from args.target
                # alone, these dropped the label, the version, the filter and
                # the repetition, so a long run's in-progress graphs were
                # overwritten by the next cell of the same daemon.
                runtime.create_bench_graphs(bench_stats, prefix=runtime.bench_output_prefix(args),
                                    results_dir=args.results_dir)


def abandon_run(runtime, reason, target, m, testers=()):
    """End a run that will not produce a result, and always raise.

    The other way out of `bench()`'s loop. `finish_bench()` stops the samplers
    on the way to publishing a row; this stops them on the way to publishing
    nothing, and the samplers are the part that must not be skipped. They are
    daemon threads polling `docker exec` once a second, and the one time they
    were left running, bgperf went on sampling through the next cell and
    **manufactured the very contention it reports** -- see
    docs/invariants/host-and-environment.md. A stop that left forty of them
    behind would do it forty times over.

    Containers are deliberately *not* removed. `bench()` already calls
    `remove_target_containers()` and `remove_old_containers()` on the way in,
    so the next run reclaims them; removing them here instead would race the
    SIGKILL that is two minutes away and could leave a half-removed container
    the next run then trips over. Leaving them is also what this repository
    does after a FAILED run, deliberately, so the wreck can be looked at.

    Raises `StopRequested` rather than returning, so nothing downstream can
    mistake an abandoned run for a row: `batch()`'s
    `completed[cell_id] = bench(a)` never executes, and the cell has no result
    document rather than one recorded as done.
    """
    m.stop_monitoring = True
    # None on a remote run, which has no target container to sample.
    if target is not None:
        target.stop_monitoring = True
    for t in testers:
        t.stop_monitoring = True
    runtime.controller_stop.set()
    print('\nabandoning this run: {0}'.format(reason))
    print('no row is recorded for it; its containers are left for the next '
          'run to reclaim')
    raise runtime.StopRequested(reason)


def finish_bench(runtime, args, output_stats, bench_stats, bench_start, target, m, testers=(), fail=False,
                 lifecycle_events=(), tester_lifecycles=None,
                 tester_observation_errors=None, tester_read_failures=None,
                 export_lifecycle=None, export_state=None,
                 export_read_failures=None, export_required=None,
                 export_receiver_names=(), export_unmeasured_reason=None,
                 export_thread=None, role_cpu=None,
                 churn_evidence=None, policy_reload_evidence=None,
                 target_table=None, target_table_unmeasured_reason=None,
                 target_table_witness_rule=None,
                 convergence_rule=None):

    bench_stop = runtime.time.time()
    output_stats['total_time'] = bench_stop - bench_start
    m.stop_monitoring = True
    target.stop_monitoring = True
    for t in testers:
        # The generator pollers watch controller_stop too, but they exec into
        # containers this run is about to walk away from, so they are told
        # twice rather than left racing the teardown.
        t.stop_monitoring = True
    runtime.controller_stop.set()

    # Wait for a receiver round still in flight before reading its recorder --
    # the poll thread is that recorder's only writer, and the round that
    # started just before convergence is the one most likely to carry the last
    # receiver's completion. It is **after** `bench_stop` on purpose, the rule
    # the tester log scan follows: `total time` is a published column that
    # `create_batch_graphs()` plots, and a wait that grows with the receiver
    # count would land in exactly the comparison the fan-out exists to make.
    #
    # Bounded because it is teardown patience, not a measurement: the longest
    # round measured on this host is 3.8s for six receivers on a loaded box,
    # and a `docker exec` that never returns must cost half a minute rather
    # than the run. A poll that has not come back is said out loud rather than
    # waited on further -- the events it holds are still published.
    export_state = export_state if export_state is not None else {}
    if export_thread is not None:
        # The only wait for this thread. An earlier revision also waited for it
        # before a post-convergence workload, and needed a guard here against
        # paying the same bound twice; that wait went away with the workload
        # interaction, and so did the guard -- a guard for a path that cannot
        # be taken reads as protection the next change would not actually have.
        wait_s = runtime.export_poll_teardown_wait_s(len(export_receiver_names or ()))
        export_thread.join(timeout=wait_s)
        if export_thread.is_alive():
            # Its own key, never `observation_error`. That key means a round
            # was *rejected* and the recorder retired, which is a different
            # finding -- and writing this note there would do more than
            # mislabel it: `observe_export_sample()` treats that key as the
            # retirement flag, so the still-running thread would silently stop
            # recording the round this note is about. Into the same dict the
            # summary reads, because a note that does not reach the artifact is
            # a note nobody gets.
            export_state['poll_incomplete'] = (
                'the receiver poll had not returned {0:.0f}s after the '
                'delivery window closed; a round still in flight may be '
                'missing from these events'.format(wait_s))

    # After `bench_stop` for the reason the receiver wait is: the final pass
    # is teardown, and `total time` is a graphed column.
    role_cpu_section = None
    if role_cpu is not None:
        role_cpu_recorder, role_cpu_thread = role_cpu
        role_cpu_thread.join(timeout=runtime.ROLE_CPU_TEARDOWN_WAIT_S)
        if role_cpu_thread.is_alive():
            role_cpu_recorder.poll_incomplete = (
                'the cgroup poll had not returned {0:.0f}s after the run '
                'ended; its last pass may be missing'.format(
                    runtime.ROLE_CPU_TEARDOWN_WAIT_S))
        role_cpu_section = role_cpu_recorder.section()

    tester_events, tester_evidence = runtime.tester_lifecycle_summary(
        tester_lifecycles or {}, tester_observation_errors or {},
        tester_read_failures or {})
    export_events, export_evidence = runtime.export_lifecycle_summary(
        export_lifecycle, export_state, export_read_failures or {},
        export_required, export_receiver_names or (),
        export_unmeasured_reason)
    lifecycle_events = list(lifecycle_events) + tester_events + list(export_events)

    bench_prefix = runtime.bench_output_prefix(args)
    artifact = runtime.write_event_artifact(
        args, lifecycle_events, bench_prefix,
        status='failed' if fail else 'converged',
        testers=tester_evidence, host=runtime.host_evidence(output_stats),
        churn=churn_evidence, policy_reload=policy_reload_evidence,
        export=export_evidence, target_table=target_table,
        target_table_unmeasured_reason=target_table_unmeasured_reason,
        target_table_witness_rule=target_table_witness_rule,
        convergence_rule=convergence_rule,
        instrument=runtime.sampler_read_failures(target, m),
        role_cpu=role_cpu_section)

    # Scan the tester logs only after the clock has stopped. These used to run
    # in bench() before bench_stop, so walking every tester log line by line --
    # twice, once per needle, over logs that reach hundreds of MB on a 1M-prefix
    # MRT run -- was billed to total_time, a column create_batch_graphs() plots.
    tester_dirs = [t.host_dir for t in testers]
    tester_class = type(testers[0]) if testers else None
    error_samples = []
    timeout_samples = []
    if tester_class is not None:
        # The matched lines are captured in the same walk that counts them.
        # Walking twice would be two reads of hundreds of MB for the second
        # copy of a number we already have, and -- since the logs are being
        # deleted out from under this by the next cell -- two different reads.
        output_stats['tester_errors'] = tester_class.find_errors(
            tester_dirs, error_samples)
        output_stats['tester_timeouts'] = tester_class.find_timeouts(
            tester_dirs, timeout_samples)
        # Inside this branch on purpose, and it was briefly outside it.
        #
        # The writer also *removes* a previous run's document, and a re-run
        # into the same --results-dir must not leave one behind -- so moving
        # the call out here looks right, and review asked for it once. It is
        # wrong. A run reaches here with no tester class whenever it built
        # no testers -- `-r/--repeat`, or a scenario that declares none (see
        # the `tester_errors` defaults above, "a run with no testers (a remote
        # target) never gets there") -- and none of those measured anything.
        # `-r` is the sharp case: `bench()` skips both
        # `remove_old_containers()` and the `shutil.rmtree(config_dir)` under
        # it, so the reused tester containers are still running and still
        # appending to the very logs nobody scanned. The zeros are the
        # defaults set before the run, not a measurement -- and removing the
        # file on the strength of them would delete a capture that still
        # describes lines present in those logs, publishing
        # `tester errors: 0` over a log that was never read.
        #
        # That is this repository's oldest rule twice over: a count of zero is
        # only published when the log proves the class was on, and a pass that
        # failed and a pass that never ran are never described by one clause.
        # A run that scanned and found nothing supersedes an earlier document;
        # a run that did not scan supersedes nothing. (That a `-r` row reports
        # `tester errors: 0` at all is a separate, older gap -- bgperf2-v6x --
        # and it is not made better by deleting the evidence.)
        runtime.write_tester_health_artifact(
            args, bench_prefix,
            output_stats.get('tester_errors', 0), error_samples,
            output_stats.get('tester_timeouts', 0), timeout_samples)

    # Read every version before the containers go away -- this is the last
    # moment any of them can be asked.
    provenance = runtime.collect_provenance(args, target, m, testers)
    del m

    target_version = provenance['target']['version']

    runtime.print_final_stats(args, target_version, output_stats)
    runtime.print_tester_metrics(lifecycle_events, tester_evidence)
    for line in runtime.describe_churn_metrics(artifact.get('churn')):
        print(line)
    for line in runtime.describe_export_metrics(artifact.get('export'),
                                        artifact.get('status')):
        print(line)
    for line in runtime.describe_policy_reload_metrics(artifact.get('policy_reload')):
        print(line)
    # Last, because it is the one line that reads the rest of them together.
    for line in runtime.describe_findings(artifact['findings']):
        print(line)
    o_s = runtime.create_output_stats(args, target_version, output_stats, fail, provenance)
    print(runtime.stats_header())
    print(','.join(map(str, o_s)))
    print()
    # it would be better to clean things up, but often I want to to investigate where things ended up
    # remove_old_containers()
    # remove_target_containers()
    runtime.create_bench_graphs(bench_stats, prefix=bench_prefix, results_dir=args.results_dir)
    runtime.write_provenance(args, provenance, bench_prefix)
    return o_s

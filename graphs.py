# creates graphs from batch output

from bgperf2 import create_batch_graphs, DEFAULT_RESULTS_DIR
from argparse import ArgumentParser

from csv import reader

if __name__ == '__main__':

    parser = ArgumentParser(description='regenerate graphs from a batch CSV')
    parser.add_argument('-f', '--filename', required=True, help='CSV written by `bgperf2.py batch`')
    parser.add_argument('-n', '--name', default='tests', help='name prefix for the generated graphs')
    parser.add_argument('--results-dir', default=DEFAULT_RESULTS_DIR,
                        help='directory for generated graphs; default: {}'.format(DEFAULT_RESULTS_DIR))

    args = parser.parse_args()

    data = []

    with open(args.filename) as f:
        csv_data = reader(f)
        for line in csv_data:
            data.append(line)
    data.pop(0) # get rid of headers
    print(f"{len(data)} tests")
    create_batch_graphs(data, args.name, results_dir=args.results_dir)

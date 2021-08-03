# creates graphs from batch output

from bgperf import create_batch_graphs
from argparse import ArgumentParser

from csv import reader

if __name__ == '__main__':
    
    parser = ArgumentParser(description='BGP performance measuring tool')
    parser.add_argument('-f', '--filename')
    parser.add_argument('-n', '--name', default='tests.csv')

    args = parser.parse_args()

    data = []

    with open(args.filename) as f:
        csv_data = reader(f)
        for line in csv_data:
            data.append(line)
    data.pop(0) # get rid of headers
    print(f"{len(data)} tests")
    create_batch_graphs(data, args.name)

import argparse
import json

import h5py
from tqdm import tqdm
import numpy as np

from mips import MIPS
from mips_sparse import MIPSSparse


def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('phrase_index_path')
    parser.add_argument('faiss_path')
    parser.add_argument('question_index_path')
    parser.add_argument('data_path')
    parser.add_argument('od_out_path')
    parser.add_argument('--cd_out_path', default="pred.json")
    parser.add_argument('--max_answer_length', default=30, type=int)
    parser.add_argument('--top_k', default=5, type=int)
    parser.add_argument('--para', default=False, action='store_true')
    parser.add_argument('--draft', default=False, action='store_true')
    parser.add_argument('--index_factory', default="IVF4096,SQ8")
    parser.add_argument('--sparse', default=False, action='store_true')
    args = parser.parse_args()
    return args


def main():
    args = get_args()

    with open(args.data_path, 'r') as fp:
        test_data = json.load(fp)
    pairs = []
    qid2text = {}
    for doc_idx, article in enumerate(test_data['data']):
        for para_idx, paragraph in enumerate(article['paragraphs']):
            for qa in paragraph['qas']:
                id_ = qa['id']
                question = qa['question']
                qid2text[id_] = question
                pairs.append([doc_idx, para_idx, id_, question])

    question_index = h5py.File(args.question_index_path)

    if not args.sparse:
        mips = MIPS(args.phrase_index_path, args.faiss_path, args.max_answer_length, load_to_memory=True, para=args.para,
                index_factory=args.index_factory)
    else:
        mips = MIPSSparse(args.phrase_index_path, args.faiss_path, args.max_answer_length, load_to_memory=True, para=args.para,
                index_factory=args.index_factory)

    vecs = []
    sparses = []
    input_idss = []
    for doc_idx, para_idx, id_, question in tqdm(pairs):
        vec = question_index[id_][0, :]
        vecs.append(vec)

        if (id_ + '_sparse') in question_index and args.sparse:
            sparse = question_index[id_ + '_sparse'][:]
            input_ids = question_index[id_ + '_input_ids'][:]
            sparses.append(sparse)
            input_idss.append(input_ids)

    query = np.stack(vecs, 0)
    if args.draft:
        query = query[:100]

    # recall at k
    cd_results = []
    od_results = []
    step_size = 10
    for i in tqdm(range(0, query.shape[0], step_size)):
        each_query = query[i:i+step_size]

        if len(sparses) > 0:
            each_sparse = sparses[i:i+step_size]
            each_input_ids = input_idss[i:i+step_size]

        if args.para:
            doc_idxs, para_idxs, _, _ = zip(*pairs[i:i+step_size])
            if len(sparses) == 0:
                each_results = mips.search(each_query, top_k=args.top_k, doc_idxs=doc_idxs, para_idxs=para_idxs)
            else:
                each_results = mips.search(each_query, top_k=args.top_k, doc_idxs=doc_idxs, para_idxs=para_idxs, q_sparse=each_sparse, q_input_ids=each_input_ids)
            cd_results.extend(each_results)

        if len(sparses) == 0:
            each_results = mips.search(each_query, top_k=args.top_k)
        else:
            each_results = mips.search(each_query, top_k=args.top_k, q_sparse=each_sparse, q_input_ids=each_input_ids)
        od_results.extend(each_results)
    top_k_answers = {query_id: [result['answer'] for result in each_results]
                     for (_, _, query_id, _), each_results in zip(pairs, od_results)}
    answers = {query_id: each_results[0]['answer']
               for (_, _, query_id, _), each_results in zip(pairs, cd_results)}

    if args.para:
        with open(args.cd_out_path, 'w') as fp:
            json.dump(answers, fp)

    with open(args.od_out_path, 'w') as fp:
        json.dump(top_k_answers, fp)


if __name__ == '__main__':
    main()

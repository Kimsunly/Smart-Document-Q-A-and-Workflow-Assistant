from sklearn.feature_extraction import DictVectorizer

measurements = [
    {'city': 'Dubai', 'temperature': 33.},
    {'city': 'London', 'temperature': 12.},
    {'city': 'San Francisco', 'temperature': 18.},
]

vec = DictVectorizer()
array = vec.fit_transform(measurements).toarray()

vec.get_feature_names_out()
print(array)
print(vec.get_feature_names_out())

data = [
    {'city': 'Phnom Penh', 'temperature': 30},
    {'city': 'Siem Reap', 'temperature': 35},
]

features = vec.fit_transform(data)

print(features)
print(vec.get_feature_names_out())

movie_entry = [{'category': ['thriller', 'drama'], 'year': 2003},
            {'category': ['animation', 'family'], 'year': 2011},
            {'year': 1974}]
vec.fit_transform(movie_entry).toarray()
vec.get_feature_names_out()
vec.transform({'category': ['thriller'],
            'unseen_feature': '3'}).toarray()
            
pos_window = [
    {
        'word-2': 'the',
        'pos-2': 'DT',
        'word-1': 'cat',
        'pos-1': 'NN',
        'word+1': 'on',
        'pos+1': 'PP',
    },
    # in a real application one would extract many such dictionaries
]

vec = DictVectorizer(sparse=False)
pos_vectorized = vec.fit_transform(pos_window)
vec.get_feature_names_out()
print(pos_vectorized)
print(vec.get_feature_names_out())